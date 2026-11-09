# Harbour Hub - Oil & Gas Marketplace

![Python](https://img.shields.io/badge/Python-3.12.6-blue.svg)
![Django](https://img.shields.io/badge/Django-4.2.23-green.svg)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Database-blue.svg)
![Redis](https://img.shields.io/badge/Redis-Cache%20%26%20Queue-red.svg)
![AWS S3](https://img.shields.io/badge/AWS%20S3-Storage-orange.svg)
![Celery](https://img.shields.io/badge/Celery-Task%20Queue-green.svg)

Harbour Hub is a comprehensive B2B marketplace platform specifically designed for the oil and gas industry. It facilitates equipment sales, rentals, and service offerings while providing robust communication tools between buyers and sellers.

## 🌟 Features

### Core Functionality

- **Equipment Listings**: Buy, rent, lease, or sell oil & gas equipment
- **Service Listings**: Find and offer specialized services
- **User Management**: Role-based access control (Buyers, Sellers, Service Providers, Admins)
- **Category Management**: Hierarchical categorization using MPTT
- **Search & Discovery**: Global search across all listings and categories
- **Inquiry System**: Direct communication between buyers and sellers
- **Storefronts**: Dedicated vendor stores with custom policies and verification
- **Commerce Engine**: Shopping carts, multi-vendor checkout, and order lifecycle
- **Financials**: Vendor wallets, automated earnings calculation, and payout tracking
- **Advanced Analytics**: Granular user behavior tracking via PostHog

### Advanced Features

- **Multi-Channel Notifications**: In-app, email, SMS via Termii, browser web push, and a staff operations webhook
- **File Management**: Support for images and documents with AWS S3 integration
- **Verification System**: Service provider verification with document upload
- **Social Login**: Google and Apple token login with verified-email checks
- **Admin Panel**: Comprehensive admin interface for platform management
- **API Documentation**: Auto-generated OpenAPI/Swagger documentation
- **Background Tasks**: Celery-powered async task processing
- **Caching**: Redis-based caching for improved performance
- **Security**: JWT authentication, rate limiting, and security headers

## 🏗️ Architecture

### Technology Stack

- **Backend**: Django 4.2.23 with Django REST Framework
- **Database**: PostgreSQL with optimized indexing
- **Cache & Queue**: Redis with Celery for background tasks
- **File Storage**: AWS S3 (configurable)
- **Authentication**: JWT tokens with refresh mechanism
- **Documentation**: DRF Spectacular (OpenAPI/Swagger)
- **Email**: SMTP with HTML templates
- **Analytics**: PostHog (Granular event tracking)
- **Monitoring**: Sentry integration

### Project Structure

```
hb/
├── apps/
│   ├── accounts/          # User management & authentication
│   ├── admin_panel/       # Admin interface & moderation
│   ├── analytics/         # Business analytics & metrics
│   ├── categories/        # Hierarchical category system
│   ├── commerce/          # Cart, checkout, orders, payments, refunds
│   ├── compliance/        # Vendor compliance documents
│   ├── core/              # Core utilities, currency, global search, sample data
│   ├── financials/        # Vendor wallets, earnings, payouts
│   ├── inquiries/         # Buyer-seller communication
│   ├── listings/          # Equipment & service listings
│   ├── messaging/         # Internal messaging system
│   ├── notifications/     # In-app notifications & delivery channels
│   ├── reviews/           # Listing and store feedback
│   ├── store/             # Vendor store management
│   └── support/           # Support tickets
├── docs/                  # API reference, data model, sample data, phase plans
├── scripts/               # Documentation generators and maintenance scripts
├── tests/                 # pytest suite
├── templates/             # Email templates
├── media/                 # User uploads
├── static/                # Static files
├── logs/                  # Application logs
└── hb/                    # Django project settings
```

## 🚀 Quick Start

### Prerequisites

- Python 3.12.6
- PostgreSQL 12+
- Redis 6+
- AWS S3 account (optional)

### Installation

1. **Clone the repository**

   ```bash
   git clone <repository-url>
   cd hb
   ```

2. **Create virtual environment**

   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Configuration**
   Create a `.env` file in the project root:

   ```env
   # Core Settings
   DEBUG=True
   SECRET_KEY=your-secret-key-here
   ENVIRONMENT=development

   # Database
   DB_NAME=harbour_hub
   DB_USER=postgres
   DB_PASSWORD=password
   DB_HOST=localhost
   DB_PORT=5432

   # Redis
   REDIS_URL=redis://localhost:6379/0

   # Email (Optional)
   EMAIL_HOST=smtp.gmail.com
   EMAIL_PORT=587
   EMAIL_HOST_USER=your-email@gmail.com
   EMAIL_HOST_PASSWORD=your-app-password

   # AWS S3 (Optional)
   USE_S3=False
   AWS_ACCESS_KEY_ID=your-access-key
   AWS_SECRET_ACCESS_KEY=your-secret-key
   AWS_STORAGE_BUCKET_NAME=your-bucket-name

   # PostHog Analytics
   POSTHOG_PROJECT_API_KEY=phc_your_key_here
   POSTHOG_HOST=https://eu.i.posthog.com
   ```

5. **Database Setup**

   ```bash
   python manage.py migrate
   ```

6. **Create Superuser**

   ```bash
   python manage.py createsuperuser
   ```

7. **Generate Sample Data (Optional)**

   Seeding is gated. The command refuses to run unless `SEED_SAMPLE_DATA=true` is set or you
   pass `--force`.

   ```bash
   # Additive run; requires SEED_SAMPLE_DATA=true in the environment
   python manage.py create_sample_data

   # One-off run without changing the environment
   python manage.py create_sample_data --force

   # Destructive reset: --clean deletes seeded business records and requires --force
   python manage.py create_sample_data --clean --force
   ```

   The dataset, its accounts, and its guarantees are documented in
   [`docs/sample-data.md`](docs/sample-data.md). Do not run `--clean` against a database whose
   data you need.

8. **Start Development Server**
   ```bash
   python manage.py runserver
   ```

### Running Background Tasks

In separate terminals:

```bash
# Celery Worker
celery -A hb worker --loglevel=info

# Celery Beat (Scheduler)
celery -A hb beat --loglevel=info
```

## 📚 API Documentation

Once the server is running, access the interactive documentation at:

- **Swagger UI**: http://localhost:8000/api/docs/
- **ReDoc**: http://localhost:8000/api/redoc/
- **OpenAPI Schema**: http://localhost:8000/api/schema/

The written reference lives in [`docs/`](docs/README.md):

| Document | What it covers |
|---|---|
| [`docs/README.md`](docs/README.md) | Documentation index and the full verification gate. |
| [`docs/api/README.md`](docs/api/README.md) | Auth, roles, pagination, error shapes, money rules, status enums, webhooks. |
| [`docs/api/examples.md`](docs/api/examples.md) | Worked request/response examples for every core flow. |
| [`docs/api/endpoints.md`](docs/api/endpoints.md) | Generated path, method, payload, and response-code reference. |
| [`docs/api/messages.md`](docs/api/messages.md) | Exact success and error strings with status codes. |
| [`docs/data-model.md`](docs/data-model.md) | Entities, relationships, invariants, and status machines. |
| [`docs/sample-data.md`](docs/sample-data.md) | The seeded dataset and how to run `create_sample_data` safely. |
| [`docs/figma-backend-gap-checklist.md`](docs/figma-backend-gap-checklist.md) | Figma frame → endpoint/model coverage map. |
| [`docs/product/future-backlog.md`](docs/product/future-backlog.md) | Advertisements, premium users, and real-time chat, with reasons for deferral. |
| [`docs/superpowers/specs/2026-11-02-harbour-hub-zero-debt-alignment-design.md`](docs/superpowers/specs/2026-11-02-harbour-hub-zero-debt-alignment-design.md) | The P5 zero-debt alignment design. |
| [`docs/superpowers/plans/2026-11-02-harbour-hub-p5-zero-debt-alignment.md`](docs/superpowers/plans/2026-11-02-harbour-hub-p5-zero-debt-alignment.md) | The P5 implementation plan. |
| [`docs/superpowers/plans/P5-COMPLETE.md`](docs/superpowers/plans/P5-COMPLETE.md) | P5 task table, gate results, and remaining staging-only checks. |

The application mounts the API at the site root. A deployment gateway may add an `/api/v1`
prefix; the paths below are the ones Django serves.

### Key API Endpoints

#### Authentication

- `POST /auth/register/` — User registration (always creates a buyer)
- `POST /auth/login/` — User login (email + password)
- `POST /auth/refresh/` — Refresh JWT token
- `GET /auth/profile/{id}/` — User profile
- `DELETE /auth/sessions/{id}/` — Remove one session (there is no `/auth/logout/` route)

#### Listings

- `GET /listings/` — List all listings
- `POST /listings/` — Create listing (seller; the store is resolved from the account)
- `GET /listings/{id}/` — Get listing details
- `PUT /listings/{id}/` — Update listing (owner only)
- `POST /listings/{id}/publish/` — Publish a draft listing

#### Categories

- `GET /categories/` — List categories
- `GET /categories/tree/` — Get category tree

#### Inquiries

- `GET /inquiries/` — List user inquiries
- `POST /inquiries/` — Send inquiry

#### Search

- `GET /search/` — Global search

#### Commerce & Orders

- `POST /commerce/cart/items/` — Add a cart item, with its own delivery address
- `POST /commerce/checkout/` — Multi-vendor checkout (initiates a Paystack transaction)
- `GET /commerce/orders/my-orders/` — Orders placed by the authenticated buyer
- `GET /commerce/orders/store-orders/` — Incoming orders for the seller's store
- `GET /commerce/orders/{id}/tracking/` — Order status and activity timeline
- `PATCH /commerce/orders/{id}/tracking/` — Seller updates tracking ID and carrier
- `POST /commerce/orders/{id}/tracking/update/` — Seller advances the order status
- `GET /quotes/sent/` — Quote requests sent by the buyer (alias: `/commerce/quotes/sent/`)
- `GET /quotes/received/` — Quote requests received by the seller (alias: `/commerce/quotes/received/`)

#### Page Feedback

- `POST /search/feedback/` — Capture Helpful/Not Helpful feedback from static pages (Legal, FAQ)

## 🎯 User Roles & Permissions

### User Types

- **Buyer**: Browse listings, send inquiries
- **Seller**: Create equipment listings, manage inquiries
- **Service Provider**: Create service listings, verification required
- **Admin**: Manage users, moderate content
- **Super Admin**: Full platform access

### Permissions Matrix

| Action           | Buyer | Seller | Service Provider | Admin |
| ---------------- | ----- | ------ | ---------------- | ----- |
| Browse listings  | ✅    | ✅     | ✅               | ✅    |
| Create listings  | ❌    | ✅     | ✅               | ✅    |
| Send inquiries   | ✅    | ✅     | ✅               | ✅    |
| Manage users     | ❌    | ❌     | ❌               | ✅    |
| Moderate content | ❌    | ❌     | ❌               | ✅    |

## 🔧 Configuration

### Environment Variables

| Variable        | Description                | Default          |
| --------------- | -------------------------- | ---------------- |
| `DEBUG`         | Debug mode                 | `False`          |
| `SECRET_KEY`    | Django secret key          | Required         |
| `DATABASE_URL`  | Database connection string | PostgreSQL local |
| `REDIS_URL`     | Redis connection string    | Required         |
| `USE_S3`        | Enable AWS S3 storage      | `False`          |
| `EMAIL_BACKEND` | Email backend              | SMTP             |
| `SENTRY_DSN`    | Sentry error tracking      | Optional         |
| `PAYSTACK_SECRET_KEY` | Paystack secret key (`sk_live_` in production) | Required for payments |
| `PAYSTACK_PUBLIC_KEY` | Paystack public key (`pk_live_` in production) | Required for payments |
| `PAYSTACK_WEBHOOK_URL` | Deployed webhook endpoint | `https://api.harbourhubglobal.com/commerce/webhooks/paystack/` |
| `SMS_PROVIDER` | SMS adapter; only `termii` is implemented | Empty (disabled) |
| `TERMII_API_KEY` | Termii API key | Empty (disabled) |
| `TERMII_SENDER_ID` | Termii sender name | `HarbourHub` |
| `VAPID_PUBLIC_KEY` | Web Push application server key | Empty (disabled) |
| `VAPID_PRIVATE_KEY` | Web Push signing key | Empty (disabled) |
| `VAPID_SUBJECT` | Web Push contact URI | `mailto:support@harbourhubglobal.com` |
| `GOOGLE_CLIENT_ID` | Google OAuth client id | Empty (disabled) |
| `APPLE_CLIENT_ID` | Apple OAuth client id | Empty (disabled) |
| `OPS_WEBHOOK_URL` | Staff operations webhook | Empty (disabled) |
| `SEED_SAMPLE_DATA` | Permit `create_sample_data` | `False` |

The complete list, with comments, lives in [`.env.example`](.env.example) and
[`.env.prod.example`](.env.prod.example). Every documented variable is read by `hb/settings.py`.

### Production Deployment

The repository ships an EC2 deployment workflow and a build script:

```bash
# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Collect static files
python manage.py collectstatic

# Start services
gunicorn hb.wsgi:application
celery -A hb worker --loglevel=info
celery -A hb beat --loglevel=info
```

The GitHub workflows are in [`.github/workflows/`](.github/workflows/); the deploy workflow reads
`EC2_HOST`, `EC2_USER`, `EC2_PATH`, and `EC2_SSH_KEY` from repository secrets.

## 🗄️ Database Schema

The complete entity map, relationships, invariants, and status machines are in
[`docs/data-model.md`](docs/data-model.md). The generated contract is
[`schema.yml`](schema.yml).

### Key Models

#### User Model

- Custom user model with role-based access
- Email-based authentication
- Profile information and verification status

#### Listing Model

- Equipment and service listings
- Support for sell/rent/lease/service types
- Rich metadata (manufacturer, model, condition)
- Image and document attachments

#### Category Model

- Hierarchical structure using MPTT
- SEO-friendly slugs
- Active/inactive status

#### Inquiry Model

- Buyer-seller communication
- Status tracking and replies
- File attachments support

## 📧 Email System

The platform includes a comprehensive email notification system:

- **Welcome emails** for new users
- **Inquiry notifications** for sellers
- **Reply notifications** for buyers
- **Password reset** functionality
- **Professional HTML templates**

Email templates are located in `templates/emails/` and use a responsive design.

## 🔍 Search & Analytics

### Search Features

- Global search across listings and categories
- Filtering by location, price, category
- Full-text search capabilities

### Analytics

- Listing performance metrics
- User engagement statistics
- Revenue tracking
- Automated reporting via Celery tasks

## 🛡️ Security Features

- **JWT Authentication** with refresh tokens
- **Rate Limiting** to prevent abuse
- **CORS Configuration** for frontend integration
- **Security Headers** (HSTS, XSS protection)
- **Input Validation** and sanitization
- **File Upload Security** with type validation

## 🧪 Testing

The suite runs on `pytest` (configured in `pytest.ini`, with `testpaths = tests`). Tests use the
`test_harbour_hub` database and an autouse fixture that pins exchange rates, so they run offline.

```bash
# Run all tests
python -m pytest -q

# Run one module
python -m pytest tests/test_checkout.py -q

# Run with coverage
coverage run -m pytest
coverage report
```

Before committing, run the full gate:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python -m pytest -q
python -m flake8 apps hb tests --select=F401,F821,F841 --exclude=migrations
python manage.py spectacular --file schema.yml --validate
```

## 📝 Management Commands

### Sample Data Generation

```bash
# Additive run; requires SEED_SAMPLE_DATA=true in the environment
python manage.py create_sample_data

# One-off run without changing the environment
python manage.py create_sample_data --force

# Custom counts
python manage.py create_sample_data --users 50 --listings 150 --orders 30

# Destructive reset; --clean requires --force
python manage.py create_sample_data --clean --force
```

See [`docs/sample-data.md`](docs/sample-data.md) for the accounts, record counts, and
determinism guarantees.

### Database Maintenance

```bash
python manage.py migrate
python manage.py collectstatic
python manage.py createsuperuser
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Development Guidelines

- Follow PEP 8 style guidelines
- Write tests for new features
- Update documentation as needed
- Use meaningful commit messages

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🆘 Support

For support and questions:

- **Email**: support@harbourhubglobal.com
- **Documentation**: Check the API docs at `/api/docs/`
- **Issues**: Use GitHub Issues for bug reports

## 🗺️ Roadmap

### Upcoming Features

- [ ] Mobile application (React Native)
- [ ] Advanced analytics dashboard
- [x] Payment integration (Paystack checkout verified and fully operational)
- [ ] Multi-language support
- [x] Advanced search filters (Listings price, condition, type, verification, and vendor rating/location filters fully operational)
- [x] Multi-channel notifications (in-app, email, Termii SMS, browser web push, staff webhook)
- [ ] API rate limiting dashboard
- [ ] Advertisements, premium users, and real-time chat (see [`docs/product/future-backlog.md`](docs/product/future-backlog.md))

---

**Harbour Hub** - Connecting the Oil & Gas Industry 🌊⚙️
