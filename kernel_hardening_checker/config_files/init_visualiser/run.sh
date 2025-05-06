#!/bin/bash

python3 kconfigs_init_parser.py ../distros -o summary.csv
python3 create_html.py -t template.html -o init_visualiser.html summary.csv

