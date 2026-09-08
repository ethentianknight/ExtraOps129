#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <tlhelp32.h>
#include <filesystem>
#include <fstream>
#include <vector>
#include <string>
#include <mutex>
#include <unordered_set>
#include <cstdint>
#include <cstring>
#include <algorithm>
#include <cwctype>
#include <array>

namespace fs = std::filesystem;
using MMRESULT = UINT;
constexpr MMRESULT TIMERR_NOERROR = 0;

struct Range {
    uint64_t offset;
    std::vector<uint8_t> expected;
    std::vector<uint8_t> replacement;
};

static HMODULE self_module;
static HMODULE real_winmm;
static fs::path package_root;
static std::once_flag request_once;
static std::vector<Range> overlay_ranges;
static bool coop_requested;
static bool overlay_ready;
static bool deck_runtime;
static std::string requested_mode;
static bool trace_enabled;
static volatile LONG create_trace_count;
static SRWLOCK handle_lock = SRWLOCK_INIT;
static std::unordered_set<HANDLE> archive_handles;

using TimerFn = MMRESULT (WINAPI *)(UINT);
using CreateFileWFn = HANDLE (WINAPI *)(LPCWSTR,DWORD,DWORD,LPSECURITY_ATTRIBUTES,DWORD,DWORD,HANDLE);
using CreateFileAFn = HANDLE (WINAPI *)(LPCSTR,DWORD,DWORD,LPSECURITY_ATTRIBUTES,DWORD,DWORD,HANDLE);
using ReadFileFn = BOOL (WINAPI *)(HANDLE,LPVOID,DWORD,LPDWORD,LPOVERLAPPED);
using CloseHandleFn = BOOL (WINAPI *)(HANDLE);
using SetFilePointerExFn = BOOL (WINAPI *)(HANDLE,LARGE_INTEGER,PLARGE_INTEGER,DWORD);

static TimerFn real_begin;
static TimerFn real_end;
static CreateFileWFn real_create_w;
static CreateFileAFn real_create_a;
static ReadFileFn real_read;
static CloseHandleFn real_close;
static SetFilePointerExFn real_seek;

static void log_line(const std::string& text) {
    if (package_root.empty()) return;
    std::ofstream stream(package_root / "state" / "runtime.log", std::ios::app);
    stream << text << "\n";
}

static void trace_line(const std::string& text) {
    if (trace_enabled) log_line("TRACE " + text);
}

static bool read_exact(std::ifstream& input, void* value, size_t size) {
    return static_cast<bool>(input.read(reinterpret_cast<char*>(value), static_cast<std::streamsize>(size)));
}

static bool load_overlay(const fs::path& path) {
    std::ifstream input(path, std::ios::binary);
    char magic[8];
    uint32_t count;
    uint64_t archive_size;
    if (!read_exact(input, magic, sizeof(magic)) || std::memcmp(magic, "EO129CO1", 8) ||
        !read_exact(input, &count, sizeof(count)) || !read_exact(input, &archive_size, sizeof(archive_size)) ||
        archive_size != 511328256 || count == 0 || count > 64) return false;
    uint64_t end = 0;
    std::vector<Range> parsed;
    parsed.reserve(count);
    for (uint32_t index = 0; index < count; ++index) {
        Range range;
        uint32_t length;
        if (!read_exact(input, &range.offset, sizeof(range.offset)) || !read_exact(input, &length, sizeof(length)) ||
            !length || range.offset < end || range.offset + length > archive_size) return false;
        range.expected.resize(length);
        range.replacement.resize(length);
        if (!read_exact(input, range.expected.data(), length) || !read_exact(input, range.replacement.data(), length)) return false;
        end = range.offset + length;
        parsed.push_back(std::move(range));
    }
    if (input.peek() != std::ifstream::traits_type::eof()) return false;
    overlay_ranges = std::move(parsed);
    return true;
}

static void load_request() {
    std::ifstream input(package_root / "state" / "deck_mode.txt");
    std::string mode;
    std::getline(input, mode);
    if (!mode.empty() && mode.back() == '\r') mode.pop_back();
    requested_mode = mode;
    deck_runtime = !mode.empty();
}

static void ensure_request() {
    std::call_once(request_once, load_request);
}

static bool target_path(const fs::path& path) {
    std::wstring text = path.lexically_normal().wstring();
    for (auto& value : text) {
        if (value == L'/') value = L'\\';
        else value = static_cast<wchar_t>(towlower(value));
    }
    const std::wstring suffix = L"\\mlg\\disc0_rel\\009645fa.pdt";
    return text.size() >= suffix.size() && text.compare(text.size() - suffix.size(), suffix.size(), suffix) == 0;
}

static bool validate_archive(HANDLE handle) {
    LARGE_INTEGER zero{}, saved{};
    if (!real_seek(handle, zero, &saved, FILE_CURRENT)) return false;
    std::vector<uint8_t> buffer(1024 * 1024);
    bool valid = true;
    for (const auto& range : overlay_ranges) {
        size_t cursor = 0;
        while (cursor < range.expected.size()) {
            DWORD amount = static_cast<DWORD>((std::min)(buffer.size(), range.expected.size() - cursor));
            LARGE_INTEGER position; position.QuadPart = static_cast<LONGLONG>(range.offset + cursor);
            if (!real_seek(handle, position, nullptr, FILE_BEGIN)) { valid = false; break; }
            DWORD read = 0;
            if (!real_read(handle, buffer.data(), amount, &read, nullptr) || read != amount ||
                std::memcmp(buffer.data(), range.expected.data() + cursor, amount)) { valid = false; break; }
            cursor += amount;
        }
        if (!valid) break;
    }
    bool restored = real_seek(handle, saved, nullptr, FILE_BEGIN) != FALSE;
    return valid && restored;
}

static void consider_archive(HANDLE handle, const fs::path& path) {
    ensure_request();
    if (handle == INVALID_HANDLE_VALUE || !coop_requested || !overlay_ready || !target_path(path)) return;
    if (!validate_archive(handle)) {
        overlay_ready = false;
        log_line("Runtime co-op overlay rejected the on-disk archive.");
        return;
    }
    AcquireSRWLockExclusive(&handle_lock);
    archive_handles.insert(handle);
    ReleaseSRWLockExclusive(&handle_lock);
    log_line("Runtime co-op archive handle verified.");
}

static HANDLE WINAPI hook_create_w(LPCWSTR name,DWORD access,DWORD share,LPSECURITY_ATTRIBUTES security,DWORD creation,DWORD flags,HANDLE templ) {
    HANDLE handle = real_create_w(name,access,share,security,creation,flags,templ);
    if (trace_enabled && InterlockedIncrement(&create_trace_count) <= 32 && name) trace_line("CreateFileW " + fs::path(name).string());
    if (name) consider_archive(handle, fs::path(name));
    return handle;
}

static HANDLE WINAPI hook_create_a(LPCSTR name,DWORD access,DWORD share,LPSECURITY_ATTRIBUTES security,DWORD creation,DWORD flags,HANDLE templ) {
    HANDLE handle = real_create_a(name,access,share,security,creation,flags,templ);
    if (trace_enabled && InterlockedIncrement(&create_trace_count) <= 32 && name) trace_line(std::string("CreateFileA ") + name);
    if (name) consider_archive(handle, fs::path(name));
    return handle;
}

static BOOL WINAPI hook_read(HANDLE handle,LPVOID buffer,DWORD requested,LPDWORD completed,LPOVERLAPPED overlapped) {
    bool tracked;
    AcquireSRWLockShared(&handle_lock);
    tracked = archive_handles.find(handle) != archive_handles.end();
    ReleaseSRWLockShared(&handle_lock);
    if (!tracked) return real_read(handle,buffer,requested,completed,overlapped);
    if (overlapped) {
        overlay_ready = false;
        log_line("Runtime co-op overlay disabled: overlapped archive read observed.");
        return real_read(handle,buffer,requested,completed,overlapped);
    }
    LARGE_INTEGER zero{}, start{};
    if (!real_seek(handle,zero,&start,FILE_CURRENT)) return real_read(handle,buffer,requested,completed,overlapped);
    BOOL result = real_read(handle,buffer,requested,completed,overlapped);
    DWORD count = completed ? *completed : 0;
    if (!result || !count || !overlay_ready) return result;
    uint64_t first = static_cast<uint64_t>(start.QuadPart), last = first + count;
    auto* bytes = static_cast<uint8_t*>(buffer);
    for (const auto& range : overlay_ranges) {
        uint64_t range_last = range.offset + range.replacement.size();
        uint64_t begin = (std::max)(first, range.offset), end = (std::min)(last, range_last);
        if (begin < end) std::memcpy(bytes + (begin - first), range.replacement.data() + (begin - range.offset), static_cast<size_t>(end - begin));
    }
    return result;
}

static BOOL WINAPI hook_close(HANDLE handle) {
    AcquireSRWLockExclusive(&handle_lock);
    archive_handles.erase(handle);
    ReleaseSRWLockExclusive(&handle_lock);
    return real_close(handle);
}

static bool patch_imports() {
    trace_line("patch_imports enter");
    HMODULE kernel = GetModuleHandleW(L"kernel32.dll");
    real_create_w = reinterpret_cast<CreateFileWFn>(GetProcAddress(kernel,"CreateFileW"));
    real_create_a = reinterpret_cast<CreateFileAFn>(GetProcAddress(kernel,"CreateFileA"));
    real_read = reinterpret_cast<ReadFileFn>(GetProcAddress(kernel,"ReadFile"));
    real_close = reinterpret_cast<CloseHandleFn>(GetProcAddress(kernel,"CloseHandle"));
    real_seek = reinterpret_cast<SetFilePointerExFn>(GetProcAddress(kernel,"SetFilePointerEx"));
    if (!real_create_w || !real_create_a || !real_read || !real_close || !real_seek) return false;
    auto* base = reinterpret_cast<uint8_t*>(GetModuleHandleW(nullptr));
    auto* dos = reinterpret_cast<IMAGE_DOS_HEADER*>(base);
    auto* nt = reinterpret_cast<IMAGE_NT_HEADERS64*>(base + dos->e_lfanew);
    auto directory = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (!directory.VirtualAddress) return false;
    auto* descriptor = reinterpret_cast<IMAGE_IMPORT_DESCRIPTOR*>(base + directory.VirtualAddress);
    for (; descriptor->Name; ++descriptor) {
        auto* names = reinterpret_cast<IMAGE_THUNK_DATA64*>(base + descriptor->OriginalFirstThunk);
        auto* slots = reinterpret_cast<IMAGE_THUNK_DATA64*>(base + descriptor->FirstThunk);
        if (!descriptor->OriginalFirstThunk) names = slots;
        for (; names->u1.AddressOfData; ++names, ++slots) {
            if (IMAGE_SNAP_BY_ORDINAL64(names->u1.Ordinal)) continue;
            auto* item = reinterpret_cast<IMAGE_IMPORT_BY_NAME*>(base + names->u1.AddressOfData);
            void* replacement = nullptr;
            if (!std::strcmp(reinterpret_cast<char*>(item->Name),"CreateFileW")) replacement = hook_create_w;
            else if (!std::strcmp(reinterpret_cast<char*>(item->Name),"CreateFileA")) replacement = hook_create_a;
            else if (!std::strcmp(reinterpret_cast<char*>(item->Name),"ReadFile")) replacement = hook_read;
            else if (!std::strcmp(reinterpret_cast<char*>(item->Name),"CloseHandle")) replacement = hook_close;
            if (!replacement) continue;
            DWORD old;
            if (!VirtualProtect(&slots->u1.Function,sizeof(uint64_t),PAGE_READWRITE,&old)) return false;
            slots->u1.Function = reinterpret_cast<uint64_t>(replacement);
            DWORD ignored; VirtualProtect(&slots->u1.Function,sizeof(uint64_t),old,&ignored);
        }
    }
    trace_line("patch_imports complete");
    return true;
}

static void load_real_winmm() {
    if (real_winmm) return;
    trace_line("load_real_winmm enter");
    wchar_t system[MAX_PATH];
    UINT length = GetSystemDirectoryW(system,MAX_PATH);
    if (!length || length >= MAX_PATH) return;
    real_winmm = LoadLibraryW((fs::path(system) / L"winmm.dll").c_str());
    if (real_winmm == self_module) real_winmm = nullptr;
    if (real_winmm) {
        real_begin = reinterpret_cast<TimerFn>(GetProcAddress(real_winmm,"timeBeginPeriod"));
        real_end = reinterpret_cast<TimerFn>(GetProcAddress(real_winmm,"timeEndPeriod"));
    }
    trace_line(std::string("load_real_winmm result=") + (real_winmm ? "loaded" : "missing"));
}

extern "C" __declspec(dllexport) MMRESULT WINAPI timeBeginPeriod(UINT period) {
    trace_line("timeBeginPeriod");
    load_real_winmm();
    return real_begin ? real_begin(period) : TIMERR_NOERROR;
}

extern "C" __declspec(dllexport) MMRESULT WINAPI timeEndPeriod(UINT period) {
    trace_line("timeEndPeriod");
    load_real_winmm();
    return real_end ? real_end(period) : TIMERR_NOERROR;
}

struct Assignment {
    int gender;
    int outfit;
    uint32_t model_a;
    uint32_t model_b;
    uint32_t original_a;
    uint32_t original_b;
};

static const std::array<std::array<uint32_t,2>,22> resource_map = {{
    {14745601,118622036},{14745602,118622127},{14745603,84019210},{14745604,84019274},
    {14745605,240257162},{14745606,240257279},{14745607,140642676},{14745608,140642759},
    {14745609,161614362},{14745610,161614476},{14745611,134351614},{14745612,134351691},
    {14745613,153226136},{14745614,153226244},{14745615,114429040},{14745616,114429104},
    {14745617,225578224},{14745618,225578327},{14745619,34737598},{14745620,34737625},
    {14745621,135400948},{14745622,135401024}
}};

static const std::array<Assignment,10> base_assignments = {{
    {1,3,14745601,14745602,4425344,3503788},{1,16,14745603,14745604,13192122,14537471},
    {1,24,14745603,14745604,8438215,14537471},{2,27,14745605,14745606,9929488,3847797},
    {2,14,14745607,14745608,1707348,7528217},{2,15,14745609,14745610,1707348,7528217},
    {2,25,14745611,14745612,7245875,6825799},{2,17,14745613,14745614,3077995,14953914},
    {2,18,14745615,14745616,3077995,14953914},{2,19,14745617,14745618,3077995,14953914}
}};

static const unsigned char selector_bytes[] = {
    0x44,0x0f,0xb6,0xd1,0x48,0x8d,0x05,0xa5,0x21,0x24,0x01,0x49,0xc1,0xe2,0x05,0x4c,
    0x03,0xd0,0x48,0x85,0xd2,0x74,0x07,0x41,0x0f,0xb7,0x02,0x66,0x89,0x02,0x4d,0x85,
    0xc0,0x74,0x09,0x41,0x0f,0xb7,0x42,0x02,0x66,0x41,0x89,0x00,0x4d,0x85,0xc9,0x74,
    0x09,0x41,0x0f,0xb7,0x42,0x04,0x66,0x41,0x89,0x01,0x48,0x8b,0x44,0x24,0x28,0x48,
    0x85,0xc0,0x74,0x09,0x41,0x0f,0x28,0x42,0x10,0x66,0x0f,0x7f,0x00,0xc3
};

static bool bytes_equal(uint8_t* address,const void* expected,size_t count) {
    return std::memcmp(address,expected,count) == 0;
}

static void append(std::vector<uint8_t>& out,std::initializer_list<uint8_t> data) {
    out.insert(out.end(),data.begin(),data.end());
}

template <typename T> static void append_value(std::vector<uint8_t>& out,T value) {
    const auto* bytes = reinterpret_cast<const uint8_t*>(&value);
    out.insert(out.end(),bytes,bytes + sizeof(value));
}

static std::vector<uint8_t> model_stub(uint8_t* base) {
    constexpr uintptr_t tail = 18916496 + (96 - 22) * 8;
    std::vector<uint8_t> out;
    append(out,{0x49,0xba}); append_value(out,reinterpret_cast<uint64_t>(base + tail));
    for (size_t index = 0; index < resource_map.size(); ++index) {
        append(out,{0x48,0xb8}); append_value(out,resource_map[index][0]); append_value(out,resource_map[index][1]);
        append(out,{0x49,0x89,0x82}); append_value(out,static_cast<uint32_t>(index * 8));
    }
    append(out,{0x33,0xc0,0x48,0x83,0xc4,0x20,0x5b,0xc3});
    return out;
}

static std::vector<uint8_t> coop_stub(uint8_t* base) {
    constexpr uintptr_t hook = 0x1f8277;
    const unsigned char tail[] = {0x44,0x3b,0xf6,0x41,0x8b,0xc6,0xbb,0x01,0,0,0,0x41,0x0f,0x4d,0xc4};
    std::vector<uint8_t> out;
    struct Fix { size_t at; int label; };
    std::vector<Fix> fix;
    std::array<size_t,4> labels{};
    auto branch=[&](uint8_t op,int label){out.push_back(op);fix.push_back({out.size(),label});out.push_back(0);};
    append(out,{0x48,0xb8}); append_value(out,reinterpret_cast<uint64_t>(base+0xea4860));
    append(out,{0x48,0x8b,0x00,0x48,0x85,0xc0});branch(0x74,0);
    append(out,{0x81,0x78,0x34,0x72,0x5f,0x6e,0x65});branch(0x75,0);
    append(out,{0x81,0x78,0x38,0x74,0x5f,0x63,0x6f});branch(0x74,1);
    append(out,{0x81,0x78,0x38,0x74,0x5f,0x70,0x72});branch(0x75,0);
    append(out,{0x81,0x78,0x3c,0x69,0x73,0x6f,0x6e});branch(0x74,2);branch(0xeb,0);
    labels[1]=out.size();append(out,{0x81,0x78,0x3c,0x6f,0x70,0x32,0x00});branch(0x75,0);
    labels[2]=out.size();append(out,{0x83,0xfe,0x02});branch(0x75,0);
    append(out,{0x41,0x83,0xfe,0x02});branch(0x72,0);append(out,{0x41,0x83,0xfe,0x03});branch(0x77,0);
    append(out,{0x44,0x89,0xf0,0x83,0xe0,0x01,0xbb,0x01,0,0,0});branch(0xeb,3);
    labels[0]=out.size();out.insert(out.end(),std::begin(tail),std::end(tail));
    labels[3]=out.size();append(out,{0xff,0x25,0,0,0,0});append_value(out,reinterpret_cast<uint64_t>(base+hook+15));
    for (const auto& item:fix) out[item.at]=static_cast<uint8_t>(static_cast<int>(labels[item.label])-static_cast<int>(item.at)-1);
    return out;
}

static bool write_bytes(void* address,const void* data,size_t size) {
    DWORD old;
    if (!VirtualProtect(address,size,PAGE_EXECUTE_READWRITE,&old)) return false;
    std::memcpy(address,data,size);FlushInstructionCache(GetCurrentProcess(),address,size);
    DWORD ignored;VirtualProtect(address,size,old,&ignored);
    return std::memcmp(address,data,size) == 0;
}

struct SuspendedThreads {
    std::vector<HANDLE> handles;
    SuspendedThreads() {
        DWORD process=GetCurrentProcessId(),current=GetCurrentThreadId();
        HANDLE snapshot=CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD,0);
        if(snapshot==INVALID_HANDLE_VALUE)return;
        THREADENTRY32 entry{sizeof(entry)};
        if(Thread32First(snapshot,&entry)) do {
            if(entry.th32OwnerProcessID==process&&entry.th32ThreadID!=current){
                HANDLE thread=OpenThread(THREAD_SUSPEND_RESUME,FALSE,entry.th32ThreadID);
                if(thread&&SuspendThread(thread)!=DWORD(-1))handles.push_back(thread);else if(thread)CloseHandle(thread);
            }
        } while(Thread32Next(snapshot,&entry));
        CloseHandle(snapshot);
    }
    ~SuspendedThreads(){for(auto thread:handles){ResumeThread(thread);CloseHandle(thread);}}
};

static std::string trim(std::string value) {
    auto first=value.find_first_not_of(" \t\r\n");if(first==std::string::npos)return {};
    auto last=value.find_last_not_of(" \t\r\n");return value.substr(first,last-first+1);
}

static std::vector<Assignment> assignments() {
    std::vector<Assignment> result(base_assignments.begin(),base_assignments.end());
    struct Slot { const char* key; int gender; int outfit; uint32_t a; uint32_t b; };
    const Slot slots[]={{"Male_Battle",1,1,10277967,2821001},{"Male_Battle_H",1,2,10277967,2821001},{"Male_Sneaking",1,0,3653363,6601267},{"Female_Battle",2,1,5327545,12997359},{"Female_Battle_H",2,2,5327545,12997359},{"Female_Sneaking",2,0,16505124,8453078}};
    std::ifstream input(package_root/L"character_config.txt");std::string line;
    while(std::getline(input,line)) {
        auto comment=line.find("//");if(comment!=std::string::npos)line.resize(comment);line=trim(line);if(line.empty())continue;
        auto colon=line.find(':');if(colon==std::string::npos)continue;std::string key=trim(line.substr(0,colon));int value=std::stoi(trim(line.substr(colon+1)));
        for(const auto& slot:slots)if(key==slot.key&&value>0){
            uint32_t id=0;if(slot.gender==1&&value<=3){const uint32_t ids[]={0,14745601,14745603,14745619};id=ids[value];}
            if(slot.gender==2&&value<=8){const uint32_t ids[]={0,14745609,14745613,14745605,14745617,14745607,14745615,14745611,14745621};id=ids[value];}
            if(id)result.push_back({slot.gender,slot.outfit,id,id+1,slot.a,slot.b});
        }
    }
    return result;
}

static bool apply_models(uint8_t* base) {
    constexpr uintptr_t hook=873582,map=18916496,tail=map+(96-22)*8,table=16345920;
    const unsigned char expected[]={0x33,0xc0,0x48,0x83,0xc4,0x20,0x5b,0xc3,0xcc,0xcc,0xcc,0xcc};
    if(!bytes_equal(base+hook,expected,sizeof(expected))||!bytes_equal(base+4289552,selector_bytes,sizeof(selector_bytes)))return false;
    auto code=model_stub(base);void* allocation=VirtualAlloc(nullptr,code.size(),MEM_COMMIT|MEM_RESERVE,PAGE_EXECUTE_READWRITE);if(!allocation)return false;
    std::memcpy(allocation,code.data(),code.size());FlushInstructionCache(GetCurrentProcess(),allocation,code.size());
    auto selected=assignments();SuspendedThreads suspended;
    for(const auto& item:selected){auto address=base+table+item.outfit*872+item.gender*8;uint32_t pair[]={item.original_a,item.original_b};if(!bytes_equal(address,pair,8))return false;}
    for(size_t index=0;index<resource_map.size()*8;++index)if(base[tail+index])return false;
    for(const auto& item:selected){uint32_t value[]={item.model_a,item.model_b};if(!write_bytes(base+table+item.outfit*872+item.gender*8,value,8))return false;}
    if(!write_bytes(base+tail,resource_map.data(),resource_map.size()*8))return false;
    unsigned char jump[12]={0x48,0xb8};std::memcpy(jump+2,&allocation,8);jump[10]=0xff;jump[11]=0xe0;
    return write_bytes(base+hook,jump,sizeof(jump));
}

static bool apply_coop_spawn(uint8_t* base) {
    constexpr uintptr_t hook=0x1f8277;
    const unsigned char expected[]={0x44,0x3b,0xf6,0x41,0x8b,0xc6,0xbb,0x01,0,0,0,0x41,0x0f,0x4d,0xc4};
    if(!bytes_equal(base+hook,expected,sizeof(expected)))return false;
    auto code=coop_stub(base);void* allocation=VirtualAlloc(nullptr,code.size(),MEM_COMMIT|MEM_RESERVE,PAGE_EXECUTE_READWRITE);if(!allocation)return false;
    std::memcpy(allocation,code.data(),code.size());FlushInstructionCache(GetCurrentProcess(),allocation,code.size());
    unsigned char jump[15]={0x48,0xb8};std::memcpy(jump+2,&allocation,8);jump[10]=0xff;jump[11]=0xe0;jump[12]=jump[13]=jump[14]=0x90;
    SuspendedThreads suspended;return write_bytes(base+hook,jump,sizeof(jump));
}

static DWORD WINAPI deck_runtime_thread(void*) {
    try {
        trace_line("runtime thread enter");
        ensure_request();
        if(!deck_runtime){trace_line("runtime thread one-shot mode; memory hooks delegated to launcher");return 0;}
        bool models=requested_mode=="models"||requested_mode=="both";
        bool coop=requested_mode=="coop"||requested_mode=="both";
        auto* base=reinterpret_cast<uint8_t*>(GetModuleHandleW(nullptr));
        auto* dos=reinterpret_cast<IMAGE_DOS_HEADER*>(base);
        auto* nt=reinterpret_cast<IMAGE_NT_HEADERS64*>(base+dos->e_lfanew);
        if(nt->OptionalHeader.SizeOfImage<=18916496+96*8){log_line("Deck executable image is unsupported.");return 5;}
        const unsigned char model_expected[]={0x33,0xc0,0x48,0x83,0xc4,0x20,0x5b,0xc3,0xcc,0xcc,0xcc,0xcc};
        const unsigned char coop_expected[]={0x44,0x3b,0xf6,0x41,0x8b,0xc6,0xbb,0x01,0,0,0,0x41,0x0f,0x4d,0xc4};
        for(int attempt=0;attempt<480;++attempt){
            bool ready=(!models||bytes_equal(base+873582,model_expected,sizeof(model_expected)))&&(!coop||bytes_equal(base+0x1f8277,coop_expected,sizeof(coop_expected)));
            if(ready)break;Sleep(250);if(attempt==479){log_line("Deck runtime patterns did not become ready.");return 1;}
        }
        if(models&&!apply_models(base)){log_line("Deck model runtime patch failed verification.");return 2;}
        if(coop&&!apply_coop_spawn(base)){log_line("Deck co-op spawn patch failed verification.");return 3;}
        log_line("Extra Ops 129 Deck runtime applied: "+requested_mode);return 0;
    } catch(const std::exception& error){log_line(std::string("Deck runtime error: ")+error.what());return 4;}
}

BOOL WINAPI DllMain(HINSTANCE module,DWORD reason,LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        self_module = module;
        DisableThreadLibraryCalls(module);
        wchar_t value[32768];
        DWORD length = GetModuleFileNameW(module,value,32768);
        if (length) package_root = fs::path(value).parent_path().parent_path() / L"Extra Ops 129";
        trace_enabled=GetFileAttributesW((package_root/L"state"/L"trace_enabled.txt").c_str())!=INVALID_FILE_ATTRIBUTES;
        trace_line("DllMain package root ready");
        wchar_t executable[MAX_PATH];
        DWORD exe_length = GetModuleFileNameW(nullptr,executable,MAX_PATH);
        if (exe_length && fs::path(executable).filename() == L"METAL GEAR SOLID PEACE WALKER.exe") {
            HANDLE thread=CreateThread(nullptr,0,deck_runtime_thread,nullptr,0,nullptr);if(thread)CloseHandle(thread);
            trace_line("DllMain runtime thread created");
        }
    }
    return TRUE;
}
