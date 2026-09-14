# Dedicated VPC Network
resource "google_compute_network" "ira_vpc" {
  name                    = var.network_name
  auto_create_subnetworks = false
  project                 = var.project_id
}

# Dedicated Subnet with Private Google Access enabled
resource "google_compute_subnetwork" "ira_subnet" {
  name                     = "${var.network_name}-subnet"
  ip_cidr_range            = var.subnet_cidr
  region                   = var.region
  network                  = google_compute_network.ira_vpc.id
  private_ip_google_access = true
  project                  = var.project_id
}

# Serverless VPC Access Connector for Cloud Run private egress
resource "google_vpc_access_connector" "serverless_connector" {
  name          = "ira-vpc-connector"
  region        = var.region
  ip_cidr_range = var.connector_cidr
  network       = google_compute_network.ira_vpc.name
  project       = var.project_id
  min_instances = 2
  max_instances = 10
  machine_type  = "e2-micro"
}

# Cloud Router & NAT for secure external egress (e.g. SEC EDGAR API)
resource "google_compute_router" "nat_router" {
  name    = "ira-nat-router"
  region  = var.region
  network = google_compute_network.ira_vpc.id
  project = var.project_id
}

resource "google_compute_router_nat" "nat_gateway" {
  name                               = "ira-nat-gateway"
  router                             = google_compute_router.nat_router.name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
  project                            = var.project_id

  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}
