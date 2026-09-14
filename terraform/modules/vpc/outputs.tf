output "network_id" {
  value = google_compute_network.ira_vpc.id
}

output "subnet_id" {
  value = google_compute_subnetwork.ira_subnet.id
}

output "connector_id" {
  value = google_vpc_access_connector.serverless_connector.id
}
