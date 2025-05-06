## Usage

1. Create csv containing gcp (public) project and image names: `gcp_all_linux_images.csv`. 
    - `./gcp_get_all_linux_images.sh` or create the csv in a different manner.
2. Start VMs and save kconfigs to GCP storage bucket.
    - e.g. `./kernel_collection.py --input gcp_all_linux_images.csv --bucket gcp-kernel-configs --concurrent 5`.

