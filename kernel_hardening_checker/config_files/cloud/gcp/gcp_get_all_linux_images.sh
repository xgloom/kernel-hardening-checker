#!/bin/bash

# Fetch GCP public image project and names. Tested on Mon May  5 11:21:50 PM UTC 2025.
# Run in GCP cloud shell.

output_file="gcp_all_linux_images.csv"

echo "project,name" > "$output_file"
gcloud compute images list \
  --filter="architecture = X86_64 AND status = READY AND NOT (family ~ '^windows-.*' OR family ~ '^sql-.*')" |
awk '
  /^NAME:/    { name = $2 }
  /^PROJECT:/ { project = $2; print project "," name }
' >> "$output_file"

