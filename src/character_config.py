from copy import deepcopy
from pathlib import Path
import re
import sys
CONFIG_PATH = (Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent) / 'character_config.txt'
SLOTS = {'Male_Battle': (1, 1, 'Battle Dress', (10277967, 2821001)), 'Male_Battle_H': (1, 2, 'Battle Dress (with helmet)', (10277967, 2821001)), 'Male_Sneaking': (1, 0, 'Sneaking Suit', (3653363, 6601267)), 'Female_Battle': (2, 1, 'Battle Dress', (5327545, 12997359)), 'Female_Battle_H': (2, 2, 'Battle Dress (with helmet)', (5327545, 12997359)), 'Female_Sneaking': (2, 0, 'Sneaking Suit', (16505124, 8453078))}
OPTIONS = {1: {1: ('Kaz', 14745601), 2: ('Kaz Swimsuit', 14745603), 3: ('Zadornov', 14745619), 4: ('Snake (High Resolution)', 14745621)}, 2: {1: ('Paz', 14745609), 2: ('Paz Swimsuit', 14745613), 3: ('Amanda', 14745605), 4: ('Amanda Sports Outfit', 14745617), 5: ('Cecile', 14745607), 6: ('Cecile Swimsuit', 14745615), 7: ('Strangelove', 14745611)}}

def parse_selections(text):
    selections = {key: 0 for key in SLOTS}
    seen = set()
    for number, line in enumerate(text.lstrip('\ufeff').splitlines(), 1):
        line = line.split('//', 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch('([A-Za-z_]+)\\s*:\\s*([0-9]+)', line)
        if not match:
            raise ValueError(f'Config line {number}: expected Setting_Name: number')
        key, value = (match[1], int(match[2]))
        if key not in SLOTS:
            raise ValueError(f'Config line {number}: unknown setting {key}')
        if key in seen:
            raise ValueError(f'Config line {number}: duplicate setting {key}')
        gender = SLOTS[key][0]
        if value != 0 and value not in OPTIONS[gender]:
            raise ValueError(f'Config line {number}: {key} accepts 0â€“{max(OPTIONS[gender])}, got {value}')
        seen.add(key)
        selections[key] = value
    return selections

def resolve_selections(base, selections):
    result = deepcopy(base)
    registered = {pair[0] for pair in result['resource_map']}
    occupied = {(a['gender'], a['outfit']) for a in result['assignments']}
    for key, value in selections.items():
        gender, outfit, name, original = SLOTS[key]
        if not value:
            continue
        if (gender, outfit) in occupied:
            raise ValueError(f'{key} conflicts with an existing roster assignment')
        character, ident = OPTIONS[gender][value]
        if not {ident, ident + 1} <= registered:
            raise ValueError(f'{character} is not included in the installed roster')
        result['assignments'].append({'gender': gender, 'outfit': outfit, 'name': name, 'models': [ident, ident + 1], 'original_models': list(original), 'setting': key, 'character': character})
        occupied.add((gender, outfit))
    result['user_selections'] = dict(selections)
    return result

def load_config(base, path=CONFIG_PATH):
    return resolve_selections(base, parse_selections(path.read_text(encoding='utf-8-sig')))
