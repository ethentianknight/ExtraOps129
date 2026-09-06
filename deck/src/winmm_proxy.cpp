#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <tlhelp32.h>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>
#include <array>
#include <cstdint>
#include <cstring>

namespace fs = std::filesystem;
using MMRESULT = UINT;
constexpr MMRESULT TIMERR_NOERROR = 0;

static HMODULE self_module;
static HMODULE real_winmm;
using TimerFn = MMRESULT (WINAPI *)(UINT);
static TimerFn real_begin;
static TimerFn real_end;

struct Assignment {
    int gender;
    int outfit;
    uint32_t model_a;
    uint32_t model_b;
    uint32_t original_a;
    uint32_t original_b;
};

static const std::array<std::array<uint32_t, 2>, 22> resource_map = {{
    {14745601,118622036},{14745602,118622127},{14745603,84019210},{14745604,84019274},
    {14745605,240257162},{14745606,240257279},{14745607,140642676},{14745608,140642759},
    {14745609,161614362},{14745610,161614476},{14745611,134351614},{14745612,134351691},
    {14745613,153226136},{14745614,153226244},{14745615,114429040},{14745616,114429104},
    {14745617,225578224},{14745618,225578327},{14745619,34737598},{14745620,34737625},
    {14745621,46271988},{14745622,46272013}
}};

static const std::array<Assignment, 11> base_assignments = {{
    {1,3,14745601,14745602,4425344,3503788},
    {1,16,14745603,14745604,13192122,14537471},
    {1,24,14745603,14745604,8438215,14537471},
    {2,27,14745605,14745606,9929488,3847797},
    {2,14,14745607,14745608,1707348,7528217},
    {2,15,14745609,14745610,1707348,7528217},
    {2,25,14745611,14745612,7245875,6825799},
    {2,17,14745613,14745614,3077995,14953914},
    {2,18,14745615,14745616,3077995,14953914},
    {2,19,14745617,14745618,3077995,14953914},
    {1,25,14745619,14745620,7245875,6825799}
}};

static const unsigned char selector_bytes[] = {
    0x44,0x0f,0xb6,0xd1,0x48,0x8d,0x05,0xa5,0x21,0x24,0x01,0x49,0xc1,0xe2,0x05,0x4c,
    0x03,0xd0,0x48,0x85,0xd2,0x74,0x07,0x41,0x0f,0xb7,0x02,0x66,0x89,0x02,0x4d,0x85,
    0xc0,0x74,0x09,0x41,0x0f,0xb7,0x42,0x02,0x66,0x41,0x89,0x00,0x4d,0x85,0xc9,0x74,
    0x09,0x41,0x0f,0xb7,0x42,0x04,0x66,0x41,0x89,0x01,0x48,0x8b,0x44,0x24,0x28,0x48,
    0x85,0xc0,0x74,0x09,0x41,0x0f,0x28,0x42,0x10,0x66,0x0f,0x7f,0x00,0xc3
};

static fs::path module_path() {
    std::wstring value(32768, L'\0');
    DWORD size = GetModuleFileNameW(self_module, value.data(), static_cast<DWORD>(value.size()));
    value.resize(size);
    return fs::path(value);
}

static void log_line(const std::string& text) {
    std::ofstream stream(module_path().parent_path() / "eo129_deck.log", std::ios::app);
    stream << text << "\n";
}

static void load_real_winmm() {
    if (real_winmm) return;
    wchar_t system[MAX_PATH];
    UINT length = GetSystemDirectoryW(system, MAX_PATH);
    if (!length || length >= MAX_PATH) return;
    fs::path path(system);
    path /= L"winmm.dll";
    real_winmm = LoadLibraryExW(path.c_str(), nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (real_winmm == self_module) real_winmm = nullptr;
    if (real_winmm) {
        real_begin = reinterpret_cast<TimerFn>(GetProcAddress(real_winmm, "timeBeginPeriod"));
        real_end = reinterpret_cast<TimerFn>(GetProcAddress(real_winmm, "timeEndPeriod"));
    }
}

extern "C" __declspec(dllexport) MMRESULT WINAPI timeBeginPeriod(UINT period) {
    load_real_winmm();
    return real_begin ? real_begin(period) : TIMERR_NOERROR;
}

extern "C" __declspec(dllexport) MMRESULT WINAPI timeEndPeriod(UINT period) {
    load_real_winmm();
    return real_end ? real_end(period) : TIMERR_NOERROR;
}

static bool bytes_equal(uint8_t* address, const void* expected, size_t count) {
    return std::memcmp(address, expected, count) == 0;
}

static void append(std::vector<uint8_t>& out, std::initializer_list<uint8_t> data) {
    out.insert(out.end(), data.begin(), data.end());
}

template <typename T> static void append_value(std::vector<uint8_t>& out, T value) {
    const auto* p = reinterpret_cast<const uint8_t*>(&value);
    out.insert(out.end(), p, p + sizeof(value));
}

static std::vector<uint8_t> model_stub(uint8_t* base) {
    constexpr uintptr_t tail = 18916496 + (96 - 22) * 8;
    std::vector<uint8_t> out;
    append(out,{0x49,0xba}); append_value(out,reinterpret_cast<uint64_t>(base + tail));
    for (size_t i=0;i<resource_map.size();++i) {
        append(out,{0x48,0xb8}); append_value(out,resource_map[i][0]); append_value(out,resource_map[i][1]);
        append(out,{0x49,0x89,0x82}); append_value(out,static_cast<uint32_t>(i*8));
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
    append(out,{0x41,0x83,0xfe,0x02});branch(0x72,0);
    append(out,{0x41,0x83,0xfe,0x03});branch(0x77,0);
    append(out,{0x44,0x89,0xf0,0x83,0xe0,0x01,0xbb,0x01,0,0,0});branch(0xeb,3);
    labels[0]=out.size();out.insert(out.end(),std::begin(tail),std::end(tail));
    labels[3]=out.size();append(out,{0xff,0x25,0,0,0,0});append_value(out,reinterpret_cast<uint64_t>(base+hook+15));
    for (const auto& item:fix) out[item.at]=static_cast<uint8_t>(static_cast<int>(labels[item.label])-static_cast<int>(item.at)-1);
    return out;
}

static bool write_bytes(void* address, const void* data, size_t size) {
    DWORD old;
    if (!VirtualProtect(address,size,PAGE_EXECUTE_READWRITE,&old)) return false;
    std::memcpy(address,data,size);
    FlushInstructionCache(GetCurrentProcess(),address,size);
    DWORD ignored;
    VirtualProtect(address,size,old,&ignored);
    return std::memcmp(address,data,size)==0;
}

struct SuspendedThreads {
    std::vector<HANDLE> handles;
    SuspendedThreads() {
        DWORD process=GetCurrentProcessId(),current=GetCurrentThreadId();
        HANDLE snapshot=CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD,0);
        if (snapshot==INVALID_HANDLE_VALUE) return;
        THREADENTRY32 entry{sizeof(entry)};
        if (Thread32First(snapshot,&entry)) do {
            if (entry.th32OwnerProcessID==process && entry.th32ThreadID!=current) {
                HANDLE thread=OpenThread(THREAD_SUSPEND_RESUME,FALSE,entry.th32ThreadID);
                if (thread && SuspendThread(thread)!=DWORD(-1)) handles.push_back(thread); else if(thread) CloseHandle(thread);
            }
        } while(Thread32Next(snapshot,&entry));
        CloseHandle(snapshot);
    }
    ~SuspendedThreads(){for(auto thread:handles){ResumeThread(thread);CloseHandle(thread);}}
};

static std::string trim(std::string value) {
    auto first=value.find_first_not_of(" \t\r\n");
    if(first==std::string::npos)return {};
    auto last=value.find_last_not_of(" \t\r\n");
    return value.substr(first,last-first+1);
}

static std::vector<Assignment> assignments(const fs::path& config_path) {
    std::vector<Assignment> result(base_assignments.begin(),base_assignments.end());
    struct Slot { const char* key; int gender; int outfit; uint32_t a; uint32_t b; };
    const Slot slots[]={{"Male_Battle",1,1,10277967,2821001},{"Male_Battle_H",1,2,10277967,2821001},{"Male_Sneaking",1,0,3653363,6601267},{"Female_Battle",2,1,5327545,12997359},{"Female_Battle_H",2,2,5327545,12997359},{"Female_Sneaking",2,0,16505124,8453078}};
    std::ifstream input(config_path);
    std::string line;
    while(std::getline(input,line)) {
        auto comment=line.find("//");if(comment!=std::string::npos)line.resize(comment);
        line=trim(line);if(line.empty())continue;
        auto colon=line.find(':');if(colon==std::string::npos)continue;
        std::string key=trim(line.substr(0,colon));int value=std::stoi(trim(line.substr(colon+1)));
        for(const auto& slot:slots) if(key==slot.key && value>0) {
            uint32_t id=0;
            if(slot.gender==1 && value<=4) {const uint32_t ids[]={0,14745601,14745603,14745619,14745621};id=ids[value];}
            if(slot.gender==2 && value<=7) {const uint32_t ids[]={0,14745609,14745613,14745605,14745617,14745607,14745615,14745611};id=ids[value];}
            if(id)result.push_back({slot.gender,slot.outfit,id,id+1,slot.a,slot.b});
        }
    }
    return result;
}

static bool apply_models(uint8_t* base,const fs::path& root) {
    constexpr uintptr_t hook=873582,map=18916496,tail=map+(96-22)*8,table=16345920;
    const unsigned char expected[]={0x33,0xc0,0x48,0x83,0xc4,0x20,0x5b,0xc3,0xcc,0xcc,0xcc,0xcc};
    if(!bytes_equal(base+hook,expected,sizeof(expected)) || !bytes_equal(base+4289552,selector_bytes,sizeof(selector_bytes)))return false;
    auto code=model_stub(base);void* allocation=VirtualAlloc(nullptr,code.size(),MEM_COMMIT|MEM_RESERVE,PAGE_EXECUTE_READWRITE);if(!allocation)return false;
    std::memcpy(allocation,code.data(),code.size());FlushInstructionCache(GetCurrentProcess(),allocation,code.size());
    auto selected=assignments(root/L"character_config.txt");
    SuspendedThreads suspended;
    for(const auto& item:selected) {
        auto address=base+table+item.outfit*872+item.gender*8;
        uint32_t expected_pair[]={item.original_a,item.original_b};
        if(!bytes_equal(address,expected_pair,8))return false;
    }
    for(size_t i=0;i<resource_map.size()*8;++i)if(base[tail+i])return false;
    for(const auto& item:selected) {uint32_t value[]={item.model_a,item.model_b};if(!write_bytes(base+table+item.outfit*872+item.gender*8,value,8))return false;}
    if(!write_bytes(base+tail,resource_map.data(),resource_map.size()*8))return false;
    unsigned char jump[12]={0x48,0xb8};std::memcpy(jump+2,&allocation,8);jump[10]=0xff;jump[11]=0xe0;
    return write_bytes(base+hook,jump,sizeof(jump));
}

static bool apply_coop(uint8_t* base) {
    constexpr uintptr_t hook=0x1f8277;
    const unsigned char expected[]={0x44,0x3b,0xf6,0x41,0x8b,0xc6,0xbb,0x01,0,0,0,0x41,0x0f,0x4d,0xc4};
    if(!bytes_equal(base+hook,expected,sizeof(expected)))return false;
    auto code=coop_stub(base);void* allocation=VirtualAlloc(nullptr,code.size(),MEM_COMMIT|MEM_RESERVE,PAGE_EXECUTE_READWRITE);if(!allocation)return false;
    std::memcpy(allocation,code.data(),code.size());FlushInstructionCache(GetCurrentProcess(),allocation,code.size());
    unsigned char jump[15]={0x48,0xb8};std::memcpy(jump+2,&allocation,8);jump[10]=0xff;jump[11]=0xe0;jump[12]=jump[13]=jump[14]=0x90;
    SuspendedThreads suspended;
    return write_bytes(base+hook,jump,sizeof(jump));
}

static std::vector<uint8_t> network_payload_stub(uint8_t* base) {
    std::vector<uint8_t> out;
    struct Fix { size_t at; int label; };
    std::vector<Fix> fix;
    std::array<size_t,3> labels{};
    auto branch=[&](uint8_t op,int label){out.push_back(op);fix.push_back({out.size(),label});out.push_back(0);};
    auto jump=[&](uintptr_t address){append(out,{0x49,0xbb});append_value(out,reinterpret_cast<uint64_t>(base+address));append(out,{0x41,0xff,0xe3});};
    append(out,{0x83,0xf8,0x03});branch(0x74,0);
    append(out,{0x80,0xbc,0x24,0x90,0x04,0x00,0x00,0x00});branch(0x75,0);
    append(out,{0x85,0xc0});branch(0x74,1);branch(0xeb,2);
    labels[0]=out.size();jump(0x6eb3b);
    labels[1]=out.size();jump(0x6eb81);
    labels[2]=out.size();jump(0x6ec4f);
    for(const auto& item:fix)out[item.at]=static_cast<uint8_t>(static_cast<int>(labels[item.label])-static_cast<int>(item.at)-1);
    return out;
}

static std::vector<uint8_t> network_flags_stub(uint8_t* base) {
    std::vector<uint8_t> out;
    append(out,{0x0f,0xb6,0x84,0x24,0x90,0x04,0x00,0x00,0xc1,0xe0,0x03,0x85,0xc0,0x74,0x03,0x83,0xc8,0x20,0x89,0x44,0x24,0x20,0x49,0xbb});
    append_value(out,reinterpret_cast<uint64_t>(base+0x6eb6d));append(out,{0x41,0xff,0xe3});
    return out;
}

static bool apply_network(uint8_t* base) {
    const unsigned char retry_expected[]={0x83,0xf8,0x01,0x7c,0x17};
    const unsigned char payload_expected[]={0x85,0xc0,0x74,0x4f,0x83,0xf8,0x03,0x0f,0x85,0x14,0x01,0x00,0x00};
    const unsigned char flags_expected[]={0x0f,0xb6,0x84,0x24,0x90,0x04,0x00,0x00,0xc1,0xe0,0x03,0x89,0x44,0x24,0x20};
    const unsigned char failed_expected[]={0x83,0xf8,0x05,0x0f,0x85,0xce,0x01,0x00,0x00};
    if(!bytes_equal(base+0x6f10f,retry_expected,sizeof(retry_expected))||!bytes_equal(base+0x6eb2e,payload_expected,sizeof(payload_expected))||!bytes_equal(base+0x6eb5e,flags_expected,sizeof(flags_expected))||!bytes_equal(base+0x6ef89,failed_expected,sizeof(failed_expected)))return false;
    HMODULE steam=GetModuleHandleW(L"steam_api64.dll");if(!steam)return false;
    using Accessor=void* (*)();using Setter=bool (*)(void*,int,int32_t);
    auto accessor=reinterpret_cast<Accessor>(GetProcAddress(steam,"SteamAPI_SteamNetworkingUtils_SteamAPI_v004"));
    auto setter=reinterpret_cast<Setter>(GetProcAddress(steam,"SteamAPI_ISteamNetworkingUtils_SetGlobalConfigValueInt32"));
    if(!accessor||!setter)return false;void* utils=nullptr;
    for(int i=0;i<480&&!utils;++i){utils=accessor();if(!utils)Sleep(250);}
    if(!utils||!setter(utils,24,60000)||!setter(utils,25,60000))return false;
    auto payload=network_payload_stub(base),flags=network_flags_stub(base);
    void* payload_memory=VirtualAlloc(nullptr,payload.size(),MEM_COMMIT|MEM_RESERVE,PAGE_EXECUTE_READWRITE);
    void* flags_memory=VirtualAlloc(nullptr,flags.size(),MEM_COMMIT|MEM_RESERVE,PAGE_EXECUTE_READWRITE);
    if(!payload_memory||!flags_memory)return false;
    std::memcpy(payload_memory,payload.data(),payload.size());std::memcpy(flags_memory,flags.data(),flags.size());
    FlushInstructionCache(GetCurrentProcess(),payload_memory,payload.size());FlushInstructionCache(GetCurrentProcess(),flags_memory,flags.size());
    unsigned char retry[]={0x83,0xf8,0x05,0x7c,0x17};
    unsigned char payload_hook[13]={0x49,0xbb};std::memcpy(payload_hook+2,&payload_memory,8);payload_hook[10]=0x41;payload_hook[11]=0xff;payload_hook[12]=0xe3;
    unsigned char flags_hook[15]={0x49,0xbb};std::memcpy(flags_hook+2,&flags_memory,8);flags_hook[10]=0x41;flags_hook[11]=0xff;flags_hook[12]=0xe3;flags_hook[13]=flags_hook[14]=0x90;
    const unsigned char failed[]={0x83,0xf8,0x04,0x0f,0x82,0xce,0x01,0x00,0x00};
    {
        SuspendedThreads suspended;
        if(!write_bytes(base+0x6f10f,retry,sizeof(retry))||!write_bytes(base+0x6eb2e,payload_hook,sizeof(payload_hook))||!write_bytes(base+0x6eb5e,flags_hook,sizeof(flags_hook))||!write_bytes(base+0x6ef89,failed,sizeof(failed)))return false;
    }
    return true;
}

static DWORD WINAPI runtime_thread(void*) {
    try {
        fs::path root=module_path().parent_path().parent_path()/L"Extra Ops 129";
        std::ifstream mode_file(root/L"state"/L"deck_mode.txt");std::string mode;std::getline(mode_file,mode);mode=trim(mode);
        bool models=mode=="models"||mode=="both",coop=mode=="coop"||mode=="both",network=true;
        if(!models&&!coop){log_line("No Deck installation mode found; runtime inactive.");return 0;}
        auto* base=reinterpret_cast<uint8_t*>(GetModuleHandleW(nullptr));
        const unsigned char model_expected[]={0x33,0xc0,0x48,0x83,0xc4,0x20,0x5b,0xc3,0xcc,0xcc,0xcc,0xcc};
        const unsigned char coop_expected[]={0x44,0x3b,0xf6,0x41,0x8b,0xc6,0xbb,0x01,0,0,0,0x41,0x0f,0x4d,0xc4};
        for(int i=0;i<480;++i) {
            bool ready=(!models||bytes_equal(base+873582,model_expected,sizeof(model_expected)))&&(!coop||bytes_equal(base+0x1f8277,coop_expected,sizeof(coop_expected)))&&(!network||base[0x6eb2e]==0x85);
            if(ready)break;
            Sleep(250);
            if(i==479){log_line("Runtime patterns did not become ready.");return 1;}
        }
        if(models&&!apply_models(base,root)){log_line("Model runtime patch failed verification.");return 2;}
        if(coop&&!apply_coop(base)){log_line("Co-op runtime patch failed verification.");return 3;}
        if(network&&!apply_network(base)){log_line("Network protocol patch failed verification.");return 5;}
        log_line("Extra Ops 129 Deck runtime applied: "+mode);
    } catch(const std::exception& error) {log_line(std::string("Runtime error: ")+error.what());return 4;}
    return 0;
}

BOOL WINAPI DllMain(HINSTANCE module,DWORD reason,LPVOID) {
    if(reason==DLL_PROCESS_ATTACH) {
        self_module=module;DisableThreadLibraryCalls(module);
        wchar_t executable[MAX_PATH];
        DWORD length=GetModuleFileNameW(nullptr,executable,MAX_PATH);
        fs::path name=length?fs::path(executable).filename():fs::path();
        if(name==L"METAL GEAR SOLID PEACE WALKER.exe") {
            HANDLE thread=CreateThread(nullptr,0,runtime_thread,nullptr,0,nullptr);if(thread)CloseHandle(thread);
        }
    }
    return TRUE;
}
