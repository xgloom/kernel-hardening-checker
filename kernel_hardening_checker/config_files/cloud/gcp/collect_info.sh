#!/bin/bash

set -e

echo "--- Starting kernel config collection script ---"

TEMP_DIR="/tmp/collect"
mkdir -p "$TEMP_DIR"

fetch_metadata() {
  curl -sfS -H "Metadata-Flavor: Google" "http://metadata.google.internal/computeMetadata/v1/$1"
}

GCS_BUCKET=$(fetch_metadata "instance/attributes/GCS_BUCKET")
IMAGE_NAME=$(fetch_metadata "instance/attributes/IMAGE_NAME")
INSTANCE_NAME=$(hostname)
ZONE=$(fetch_metadata "instance/zone" | cut -d'/' -f4)
PROJECT=$(fetch_metadata "project/project-id")

echo "Configuration: Bucket=$GCS_BUCKET, Image=$IMAGE_NAME"

OUTPUT_DIR="${TEMP_DIR}/${IMAGE_NAME}"
mkdir -p "$OUTPUT_DIR"

echo "Collecting system information..."
SYSTEM_INFO_FILE="${OUTPUT_DIR}/system_info.txt"

{
  echo "VM System Information"
  echo "Collection Date: $(date)"
  echo "VM Hostname: $(hostname)"
  echo "Image Used: ${IMAGE_NAME}"
  
  echo ""
  echo "COMMAND: uname -a"
  uname -a
  
  echo ""
  echo "COMMAND: lscpu"
  lscpu
  
  echo ""
  echo "COMMAND: cat /etc/*-release"
  cat -v /etc/*-release 2>/dev/null || echo "No release files found"
} > "${SYSTEM_INFO_FILE}"

echo "Collecting kernel configuration..."
CONFIG_FILE="${OUTPUT_DIR}/${IMAGE_NAME}.config"

{
  echo "# Kernel configuration for ${IMAGE_NAME}"
  echo "# Collection Date: $(date)"
  echo "# Kernel Version: $(uname -r)"
  echo ""
  
  KERNEL_VERSION=$(uname -r)
  PRIMARY_CONFIG_FILE="/boot/config-${KERNEL_VERSION}"
  PROC_CONFIG_FILE="/proc/config.gz"
  
  if [ -f "$PRIMARY_CONFIG_FILE" ]; then
    echo "# source: $PRIMARY_CONFIG_FILE"
    cat "$PRIMARY_CONFIG_FILE"
  elif [ -f "$PROC_CONFIG_FILE" ]; then
    echo "# source: $PROC_CONFIG_FILE (gzipped)"
    if command -v zcat &> /dev/null; then
      zcat "$PROC_CONFIG_FILE"
    else
      echo "# error: zcat command not found, cannot display $PROC_CONFIG_FILE"
    fi
  else
    echo "# searching for alternative config locations..."
    ALT_CONFIG_PATH=$(find /boot /lib/modules/"${KERNEL_VERSION}" \( -name 'config' -o -name "config-*" \) -type f -print -quit 2>/dev/null)
    if [ -n "$ALT_CONFIG_PATH" ] && [ -f "$ALT_CONFIG_PATH" ]; then
      echo "# source: $ALT_CONFIG_PATH"
      cat "$ALT_CONFIG_PATH"
    else
      echo "# kernel config file not found in common locations."
    fi
  fi
} > "${CONFIG_FILE}"

echo "Uploading files to GCS bucket..."

TOKEN=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)

upload_file() {
  local file_path="$1"
  local file_name=$(basename "$file_path")
  local upload_path="${IMAGE_NAME}/${file_name}"
  
  echo "Uploading $file_name..."
  
  RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" \
       -X POST --data-binary @"$file_path" \
       -H "Authorization: Bearer ${TOKEN}" \
       -H "Content-Type: application/octet-stream" \
       "https://storage.googleapis.com/upload/storage/v1/b/${GCS_BUCKET}/o?name=${upload_path}&uploadType=media")
  
  if [ "$RESPONSE" -ge 200 ] && [ "$RESPONSE" -lt 300 ]; then
    echo "✓ Upload successful for $file_name"
    return 0
  else
    echo "✗ Upload failed for $file_name with response code $RESPONSE"
    return 1
  fi
}

UPLOAD_SUCCESS=false
if upload_file "$SYSTEM_INFO_FILE" && upload_file "$CONFIG_FILE"; then
  UPLOAD_SUCCESS=true
fi

if [ "$UPLOAD_SUCCESS" = true ]; then
  echo "=== All files uploaded successfully ==="
  
  # set metadata to signal successful completion.
  curl -s -X POST \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"fingerprint\":\"$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/metadata/fingerprint)\"," \
    -d "\"items\":[{\"key\":\"completion-status\",\"value\":\"success\"}]}" \
    "https://compute.googleapis.com/compute/v1/projects/${PROJECT}/zones/${ZONE}/instances/${INSTANCE_NAME}/setMetadata" > /dev/null
    
  echo "--- VM SCRIPT COMPLETE AND UPLOAD SIGNALED ---"
else
  echo "=== Upload failed, check logs ==="
fi

exit 0
