#!/usr/bin/env python3
"""
Parse kernel config files to extract stack and heap initialization settings.
"""
import csv
import argparse
from pathlib import Path
from typing import Dict, Set, Optional

# config option mappings
STACK_OPTIONS = {
    'CONFIG_INIT_STACK_NONE': 'none',
    'CONFIG_INIT_STACK_ALL_PATTERN': 'pattern',
    'CONFIG_INIT_STACK_ALL_ZERO': 'zero'
}
HEAP_OPTION = 'CONFIG_INIT_ON_ALLOC_DEFAULT_ON'
DEFAULT_VALUE = 'unknown'


def get_config_status(option: str, config_lines: Set[str]) -> Optional[bool]:
    if f"{option}=y" in config_lines:
        return True
    if f"# {option} is not set" in config_lines:
        return False
    return None


def parse_config(path: Path) -> Dict[str, str]:
    try:
        config_lines = {line.strip() for line in path.read_text(errors='ignore').splitlines()}
        
        # stack.
        init_stack = DEFAULT_VALUE
        for option, value in STACK_OPTIONS.items():
            if get_config_status(option, config_lines) is True:
                init_stack = value
                break
        
        if (init_stack == DEFAULT_VALUE and 
            all(get_config_status(opt, config_lines) is False for opt in STACK_OPTIONS)):
            init_stack = 'none'
        
        # heap.
        heap_status = get_config_status(HEAP_OPTION, config_lines)
        init_heap = 'zero' if heap_status is True else 'none' if heap_status is False else DEFAULT_VALUE
        
        return {
            'name': path.stem,
            'init_stack': init_stack,
            'init_heap': init_heap,
        }
    except Exception as e:
        print(f"Error processing {path}: {e}")
        return {'name': path.stem, 'init_stack': DEFAULT_VALUE, 'init_heap': DEFAULT_VALUE}


def main(input_dir: Path, output_csv: Path) -> None:
    """Process config files and write summary to CSV."""
    configs = sorted(input_dir.glob('*.config'))
    if not configs:
        print(f"No .config files found in {input_dir}")
        return
    
    with output_csv.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['name', 'init_stack', 'init_heap'])
        writer.writeheader()
        for cfg in configs:
            writer.writerow(parse_config(cfg))
    
    print(f"Written summary to {output_csv}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Summarize CONFIG_INIT* settings in kernel config files')
    parser.add_argument('input_dir', type=Path, help='Directory containing .config files')
    parser.add_argument('-o', '--output', dest='output_csv', type=Path, default=Path('summary.csv'),
                        help='Output CSV file (default: summary.csv)')
    args = parser.parse_args()
    main(args.input_dir, args.output_csv)

