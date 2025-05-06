#!/usr/bin/env python3
import os
import argparse
import pandas as pd
from jinja2 import Template, FileSystemLoader, Environment

def create_html_from_csv(csv_path, template_path, output_path):
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV file not found: {csv_path}")
    
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Template file not found: {template_path}")
    
    df = pd.read_csv(csv_path)
    
    table_html = df.to_html(
        classes=['display', 'nowrap'], 
        table_id='dataTable', 
        index=False,
        border=0
    )
    
    template_dir = os.path.dirname(os.path.abspath(template_path))
    template_file = os.path.basename(template_path)
    
    with open(template_path, 'r') as f:
        template_str = f.read()
    
    template = Template(template_str)
    html_content = template.render(
        table_html=table_html
    )
    
    with open(output_path, 'w') as f:
        f.write(html_content)
    
    print(f"Successfully created {output_path} from {csv_path}")
    print(f"Open it in your browser with: {os.path.abspath(output_path)}")

def main():
    parser = argparse.ArgumentParser(description='Convert CSV to HTML with DataTables')
    parser.add_argument('csv_file', help='Path to the CSV file')
    parser.add_argument('--template', '-t', default='template.html', 
                        help='Path to the HTML template (default: template.html)')
    parser.add_argument('--output', '-o', help='Output HTML file path')
    
    args = parser.parse_args()
    
    # set default output filename based on input if not specified
    if not args.output:
        base_name = os.path.splitext(os.path.basename(args.csv_file))[0]
        args.output = f"{base_name}.html"
    
    create_html_from_csv(args.csv_file, args.template, args.output)

if __name__ == "__main__":
    main()
