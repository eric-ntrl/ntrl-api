# NTRL API

Neutral News Backend API - A content processing system that ingests news articles and applies neutrality analysis.

## Features

- Ingest news articles from RSS feeds (AP News) or direct submission
- Generate neutral summaries of potentially biased content
- Analyze articles for bias terms, political lean, and reading level
- Provide "redline" highlighting showing biased language
- Serve a public feed API for processed articles

## Tech Stack

- **Framework**: FastAPI
- **Database**: PostgreSQL
- **ORM**: SQLAlchemy 2.x
- **Migrations**: Alembic

## Setup

### Prerequisites

- Python 3.11+
- PostgreSQL
- pipenv

### Installation

1. Clone the repository:
   ```bash
   git clone git@github.com:xbcinc/ntrl-api.git
   cd ntrl-api
   ```

2. Install dependencies:
   ```bash
   pipenv install
   ```

3. Set up environment variables:
   ```bash
   cp .env.example .env
   # Edit .env with your database credentials
   ```

4. Create the database:
   ```bash
   createdb ntrl_dev
   ```

5. Run migrations:
   ```bash
   pipenv run migrate
   ```

### Running the Server

Development mode (with auto-reload):
```bash
pipenv run dev
```

Production mode:
```bash
pipenv run start
```

The API will be available at `http://localhost:8000`

## API Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/health` | GET | - | Health check |
| `/feed` | GET | - | Public feed of processed articles |
| `/articles/{id}` | GET | - | Article detail with redlined HTML |
| `/admin/ping` | GET | Admin API Key | Admin verification |
| `/pipeline/ping` | GET | Pipeline API Key | Pipeline verification |
| `/pipeline/run` | POST | Pipeline API Key | Process single article |
| `/pipeline/ingest/ap` | POST | Pipeline API Key | Bulk ingest AP News |

## API Documentation

Once running, visit:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Development

### Running Tests

```bash
pipenv install --dev
pipenv run pytest
```

### Creating Migrations

```bash
pipenv run alembic revision --autogenerate -m "Description of changes"
pipenv run migrate
```

## Project Structure

```
ntrl-api/
├── app/
│   ├── main.py             # FastAPI app & endpoints
│   ├── database.py         # SQLAlchemy setup
│   ├── models.py           # ORM models
│   ├── pipeline_service.py # Core processing logic
│   ├── articles.py         # Article detail endpoint
│   └── rss_ingest.py       # RSS ingestion
├── migrations/
│   └── versions/           # Alembic migrations
├── alembic.ini
├── Pipfile
└── README.md
```

## License

Proprietary
