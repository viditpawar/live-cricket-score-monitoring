# Live Cricket Score Monitoring Stack

A DevOps monitoring project that instruments a Flask-based cricket score API and monitors it using Prometheus and Grafana.

This project demonstrates application observability, containerized deployment, metrics instrumentation, and alerting using modern DevOps tools.

---

## Architecture

Users  
↓  
Flask Cricket Score API  
↓  
Prometheus (Metrics Collection)  
↓  
Grafana (Visualization Dashboards)  
↓  
Alert Rules (Service Monitoring)

---

## Tech Stack

- Python
- Flask
- Docker
- Docker Compose
- Prometheus
- Grafana
- PromQL
- REST APIs

---

## Features

- Flask API for live cricket score data
- Prometheus metrics instrumentation
- Custom metrics for request tracking
- Grafana dashboards for visualization
- Alert rules for service monitoring
- Fully containerized deployment using Docker Compose

---

## Project Structure
live-cricket-score-monitoring
│
├─ app
│ └─ src
│ └─ app.py
│
├─ monitoring
│ ├─ grafana
│ │ ├─ dashboards
│ │ └─ provisioning
│ │
│ └─ prometheus
│ ├─ prometheus.yml
│ └─ alert.rules.yml
│
├─ docs
│ └─ screenshots
│
├─ Dockerfile
├─ docker-compose.yml
├─ requirements.txt
└─ README.md


---

## Running the Project

Clone the repository


---

## Running the Project

Clone the repository

git clone <your-repo-url>
cd live-cricket-score-monitoring


Start the monitoring stack


docker compose up --build


Access the services

Flask API


http://localhost:5000


Prometheus


http://localhost:9090


Grafana


http://localhost:3000


---

## Screenshots

### Grafana Dashboard

![Grafana Dashboard](docs/screenshots/grafana-dashboard.png)

### Prometheus Targets

![Prometheus Targets](docs/screenshots/prometheus-targets.png)

### Prometheus Alerts

![Prometheus Alerts](docs/screenshots/prometheus-alerts.png)

### Docker Containers

![Docker Containers](docs/screenshots/docker-containers.png)

---

## Monitoring Metrics

Example metrics collected:

- `flask_http_request_total`
- `live_score_requests_total`
- `cricket_api_requests_total`
- `cricket_api_failures_total`
- `cricket_api_response_time_seconds`

---

## Alert Rules

Prometheus alert rules detect:

- Application downtime
- Cricket API failures
- High API response time

---

## Future Improvements

- Node Exporter for system metrics
- Alertmanager integration (Slack/Email alerts)
- Kubernetes deployment