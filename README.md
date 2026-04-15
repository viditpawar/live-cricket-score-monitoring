# Live Cricket Score Monitoring

![Python](https://img.shields.io/badge/Python-3.11-blue)
![Flask](https://img.shields.io/badge/Framework-Flask-green)
![Docker](https://img.shields.io/badge/Container-Docker-blue)
![Prometheus](https://img.shields.io/badge/Monitoring-Prometheus-orange)
![Grafana](https://img.shields.io/badge/Dashboard-Grafana-yellow)

A Dockerized observability stack for a Flask-based live cricket score API.
It collects custom Prometheus metrics, evaluates alert rules, and visualizes data in Grafana.

## Architecture

![Architecture Diagram](docs/diagrams/architecture.svg)

Flow summary: `Users -> Flask API -> Prometheus -> Grafana`, with Flask also fetching live match data from CricAPI.

## Features

- Live cricket match and score endpoints using CricAPI
- Built-in Flask + custom Prometheus metrics
- Prometheus alert rules for uptime, failures, and latency
- Grafana integration for dashboard visualization
- One-command local startup with Docker Compose

## Tech Stack

- Python 3.11
- Flask
- Requests
- Prometheus + PromQL
- Grafana
- Docker + Docker Compose

## Project Structure

```text
live-cricket-score-monitoring/
|- app/
|  `- src/
|     `- app.py
|- monitoring/
|  |- prometheus/
|  |  |- prometheus.yml
|  |  `- alert.rules.yml
|  `- grafana/
|     |- dashboards/
|     `- provisioning/
|- docs/
|  |- diagrams/
|  `- screenshots/
|- Dockerfile
|- docker-compose.yml
|- requirements.txt
`- README.md
```

## Prerequisites

- Docker Desktop (or Docker Engine + Compose plugin)
- A valid CricAPI API key

## Quick Start

1. Clone the repository:

```bash
git clone https://github.com/viditpawar/live-cricket-score-monitoring
cd live-cricket-score-monitoring
```

2. Create a `.env` file in the project root:

```env
CRICKET_API_KEY=your_api_key_here
```

3. Start the stack:

```bash
docker compose up --build
```

4. Open the services:

- Flask API: http://localhost:5000
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000

Grafana default login is typically `admin` / `admin` on first run (you may be prompted to change the password).

## API Endpoints

- `GET /` - Basic service message
- `GET /health` - Health check
- `GET /config-check` - Confirms API key is loaded
- `GET /matches` - Returns simplified current matches
- `GET /live-score` - Returns one live score (supports `?match_name=india`)
- `GET /metrics` - Prometheus metrics endpoint

## Metrics Collected

- `flask_http_request_total`
- `live_score_requests_total`
- `cricket_api_requests_total`
- `cricket_api_failures_total`
- `cricket_api_response_time_seconds`

## Alert Rules

Configured alerts include:

- `FlaskAppDown`
- `CricketApiFailuresDetected`
- `HighCricketApiResponseTime`

## Grafana Dashboard

A dashboard JSON export is available at:

`monitoring/grafana/dashboards/Live Cricket Score App Monitoring-1776234168280.json`

If it does not auto-load in Grafana, import it manually from the Grafana UI:

`Dashboards -> New -> Import`

## Screenshots

### Grafana Dashboard

![Grafana Dashboard](docs/screenshots/grafana-dashboard.png)

### Prometheus Targets

![Prometheus Targets](docs/screenshots/prometheus-targets.png)

### Prometheus Alerts

![Prometheus Alerts](docs/screenshots/prometheus-alerts.png)

### Docker Containers

![Docker Containers](docs/screenshots/docker-containers.png)

## Future Improvements

- Add Alertmanager notifications (Slack/Email)
- Add Node Exporter/cAdvisor for infrastructure metrics
- Deploy on Kubernetes
