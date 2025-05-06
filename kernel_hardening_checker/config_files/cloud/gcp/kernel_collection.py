#!/usr/bin/env python3

import argparse
import csv
import os
import subprocess
import sys
import time
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import random
import string

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("kernel_collection.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

DEFAULT_ZONE = "us-central1-a"
DEFAULT_MAX_CONCURRENT = 5
DEFAULT_TIMEOUT = 300

def run_command(cmd, check=True):
    result = subprocess.run(cmd, shell=True, check=check, text=True, 
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.stdout.strip(), result.stderr.strip()

def ensure_gcs_bucket(bucket_name):
    output, _ = run_command(f"gsutil ls -b gs://{bucket_name}", check=False)
    
    if "BucketNotFoundException" in output or not output:
        logger.info(f"Creating GCS bucket: {bucket_name}")
        
        project, _ = run_command("gcloud config get-value project")
        project = project.strip()
        
        if not project:
            logger.error("Could not determine GCP project ID")
            sys.exit(1)
            
        run_command(f"gsutil mb -p {project} gs://{bucket_name}")
        run_command(f"gsutil versioning set on gs://{bucket_name}")
        
        lifecycle_config = """
        {
          "rule": [
            {
              "action": {"type": "Delete"},
              "condition": {"age": 14}
            }
          ]
        }
        """
        
        with open('/tmp/lifecycle.json', 'w') as f:
            f.write(lifecycle_config)
            
        run_command(f"gsutil lifecycle set /tmp/lifecycle.json gs://{bucket_name}")
        os.remove('/tmp/lifecycle.json')
        
        logger.info(f"Bucket gs://{bucket_name} created and configured")
    else:
        logger.info(f"Using existing bucket: gs://{bucket_name}")

def check_vm_completion(vm_name, image_name, gcp_zone, gcs_bucket):
    check_cmd = f"gsutil ls gs://{gcs_bucket}/{image_name}/ 2>/dev/null || echo 'No files found'"
    ls_output, _ = run_command(check_cmd, check=False)
    
    if "system_info.txt" in ls_output and f"{image_name}.config" in ls_output:
        logger.info(f"Files found in GCS for {image_name}")
        return True
    
    metadata_cmd = f"gcloud compute instances describe {vm_name} --zone={gcp_zone} --format='json(metadata.items)'"
    metadata, _ = run_command(metadata_cmd, check=False)
    
    if '"key": "completion-status", "value": "success"' in metadata:
        logger.info(f"Success metadata found for VM '{vm_name}'")
        return True
    
    return False

def create_vm(image_name, image_project, gcp_zone, collector_script, gcs_bucket, timeout):
    # create sanitized VM name.
    vm_name = f"temp-collect-{image_name}"
    vm_name = ''.join(c if c.isalnum() or c in '._-' else '-' for c in vm_name)
    vm_name = vm_name.replace(':/','').replace('.', '-')
    vm_name = vm_name[:63]
    if vm_name.endswith('-'):
        vm_name = vm_name[:-1]
    
    logger.info(f"Processing Image: {image_name} from project {image_project}")
    logger.info(f"Generated VM Name: {vm_name}")
    
    try:
        # provide target VM with collector script and other necessary metadata.
        cmd = f"""
        gcloud compute instances create "{vm_name}" \
          --zone="{gcp_zone}" \
          --image="{image_name}" \
          --image-project="{image_project}" \
          --machine-type=e2-micro \
          --metadata-from-file startup-script="{collector_script}" \
          --metadata GCS_BUCKET="{gcs_bucket}",IMAGE_NAME="{image_name}" \
          --scopes=https://www.googleapis.com/auth/devstorage.read_write,https://www.googleapis.com/auth/compute \
          --quiet
        """
        output, error = run_command(cmd, check=False)
        
        if "ERROR" in error or "ERROR" in output:
            logger.error(f"Failed to create VM {vm_name}. Skipping.")
            logger.error(error)
            return False
            
        logger.info(f"VM '{vm_name}' created. Waiting for task completion...")
        
        start_time = time.time()
        completion_signal = False
        
        while True:
            elapsed_time = time.time() - start_time
            
            if elapsed_time > timeout:
                logger.warning(f"TIMEOUT: VM '{vm_name}' did not complete within {timeout} seconds.")
                break
                
            if check_vm_completion(vm_name, image_name, gcp_zone, gcs_bucket):
                logger.info(f"Completion confirmed for VM '{vm_name}'.")
                completion_signal = True
                break
                
            logger.info(f"Still waiting for VM '{vm_name}' to complete... ({int(elapsed_time)}s / {timeout}s)")
            time.sleep(20)
            
        logger.info(f"Deleting VM '{vm_name}'...")
        run_command(f"gcloud compute instances delete {vm_name} --zone={gcp_zone} --quiet", check=False)
        
        if not completion_signal:
            logger.warning(f"Warning: VM '{vm_name}' may not have completed successfully.")
            return False
            
        logger.info(f"Finished processing Image: {image_name}")
        return True
        
    except Exception as e:
        logger.error(f"Error processing VM {vm_name}: {str(e)}")
        run_command(f"gcloud compute instances delete {vm_name} --zone={gcp_zone} --quiet", check=False)
        return False

def process_images(csv_file, gcs_bucket, gcp_zone, max_concurrent, collector_script, timeout):
    if not os.path.isfile(collector_script):
        logger.error(f"Collector script file '{collector_script}' not found.")
        sys.exit(1)
        
    if not os.path.isfile(csv_file):
        logger.error(f"CSV file '{csv_file}' not found.")
        sys.exit(1)
    ensure_gcs_bucket(gcs_bucket)
    
    images = []
    with open(csv_file, 'r') as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            if len(row) >= 2 and row[1].strip():
                images.append((row[0].strip(), row[1].strip()))
    
    if not images:
        logger.error("No valid images found in CSV file.")
        sys.exit(1)
        
    logger.info(f"Found {len(images)} images to process")
    
    successful = 0
    failed = 0
    
    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        futures = [
            executor.submit(create_vm, image_name, image_project, gcp_zone, collector_script, gcs_bucket, timeout)
            for image_project, image_name in images
        ]
        
        for future in futures:
            if future.result():
                successful += 1
            else:
                failed += 1
    
    logger.info(f"All images processed. Successful: {successful}, Failed: {failed}")
    logger.info(f"Results are available in GCS bucket: gs://{gcs_bucket}/")

def main():
    parser = argparse.ArgumentParser(description="Linux Kernel Config Collection Tool")
    parser.add_argument("-i", "--input", dest="csv_file", default="linux_images.csv",
                        help="Specify the CSV input file")
    parser.add_argument("-b", "--bucket", dest="gcs_bucket", 
                        default=f"linux-kconfig-{time.strftime('%Y%m%d')}-{''.join(random.choices(string.ascii_lowercase + string.digits, k=6))}",
                        help="Specify GCS bucket name")
    parser.add_argument("-z", "--zone", dest="gcp_zone", default=DEFAULT_ZONE,
                        help="Specify GCP zone")
    parser.add_argument("-c", "--concurrent", dest="max_concurrent", type=int, default=DEFAULT_MAX_CONCURRENT,
                        help="Maximum number of concurrent VMs")
    parser.add_argument("-t", "--timeout", dest="timeout", type=int, default=DEFAULT_TIMEOUT,
                        help="Timeout in seconds for VM operations")
    
    args = parser.parse_args()
    
    print("--- Linux Kernel Config Collection Tool ---")
    print()
    
    collector_script = "collect_info.sh"
    if not os.path.isfile(collector_script):
        logger.error(f"Collector script file '{collector_script}' not found.")
        sys.exit(1)
        
    try:
        subprocess.run(["gcloud", "--version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.error("gcloud command not found. Please install Google Cloud SDK.")
        sys.exit(1)
        
    project, _ = run_command("gcloud config get-value project", check=False)
    project = project.strip()
    
    if not project:
        logger.error("GCP project not set. Please run 'gcloud config set project YOUR_PROJECT_ID'")
        sys.exit(1)
        
    print(f"Configuration Summary:")
    print(f"  - Input CSV: {args.csv_file}")
    print(f"  - GCS Bucket: {args.gcs_bucket}")
    print(f"  - GCP Zone: {args.gcp_zone}")
    print(f"  - Max Concurrent VMs: {args.max_concurrent}")
    print(f"  - VM Timeout: {args.timeout} seconds")
    print(f"  - GCP Project: {project}")
    print()
    
    response = input("Do you want to proceed with these settings? (y/n): ").strip().lower()
    if response != 'y':
        print("Operation cancelled by user.")
        sys.exit(0)
    
    print("Starting collection process...")
    process_images(args.csv_file, args.gcs_bucket, args.gcp_zone, 
                  args.max_concurrent, collector_script, args.timeout)
    
    print()
    print(f"Collection complete! Results available in GCS bucket: gs://{args.gcs_bucket}/")
    print(f"You can download all results with: gsutil -m cp -r gs://{args.gcs_bucket}/ .")
    print()

if __name__ == "__main__":
    main()

