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

- **Email Notifications**: Automated email system for inquiries and updates
- **File Management**: Support for images and documents with AWS S3 integration
- **Verification System**: Service provider verification with document upload
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
│   ├── core/             # Core utilities & global search
│   ├── health/           # Health checks
│   ├── inquiries/        # Buyer-seller communication
│   ├── listings/         # Equipment & service listings
│   ├── commerce/         # Orders, payments, and checkout
│   ├── financials/       # Vendor wallets & earnings
│   ├── store/            # Vendor store management
│   ├── reviews/          # Listing and store feedback
│   ├── notifications/    # In-app notification system
│   └── messaging/        # Internal messaging system
├── templates/            # Email templates
├── media/               # User uploads
├── static/              # Static files
├── logs/                # Application logs
└── hb/                  # Django project settings
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

   ```bash
   # Generates users, stores, listings, inquiries, orders, and financial records
   python manage.py create_sample_data
   
   # Use --clean to wipe existing data first
   python manage.py create_sample_data --clean
   ```

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

Once the server is running, access the API documentation at:

- **Swagger UI**: http://localhost:8000/api/docs/
- **ReDoc**: http://localhost:8000/api/redoc/
- **OpenAPI Schema**: http://localhost:8000/api/schema/

### Key API Endpoints

#### Authentication

- `POST /api/v1/auth/login/` - User login
- `POST /api/v1/auth/refresh/` - Refresh JWT token
- `POST /api/v1/auth/register/` - User registration
- `GET /api/v1/auth/profile/` - User profile

#### Listings

- `GET /api/v1/listings/` - List all listings
- `POST /api/v1/listings/` - Create listing (authenticated)
- `GET /api/v1/listings/{id}/` - Get listing details
- `PUT /api/v1/listings/{id}/` - Update listing (owner only)

#### Categories

- `GET /api/v1/categories/` - List categories
- `GET /api/v1/categories/tree/` - Get category tree

#### Inquiries

- `GET /api/v1/inquiries/` - List user inquiries
- `POST /api/v1/inquiries/` - Send inquiry

#### Search

- `GET /api/v1/search/` - Global search

#### Commerce & Orders

- `POST /api/v1/checkout/` - Multi-vendor cart checkout (initiates Paystack transaction)
- `GET /api/v1/orders/my-orders/` - List orders placed by the authenticated buyer
- `GET /api/v1/orders/store-orders/` - List incoming orders for the seller's store
- `GET /api/v1/orders/{id}/tracking/` - Retrieve real-time status and activity timeline for an order
- `PATCH /api/v1/orders/{id}/tracking/` - Seller updates order tracking ID and carrier info
- `POST /api/v1/orders/{id}/tracking/update/` - Seller updates status and appends custom timeline events
- `GET /api/v1/quotes/sent/` - List quote requests sent by the buyer
- `GET /api/v1/quotes/received/` - List quote requests received by the seller's store

#### Page Feedback

- `POST /api/v1/feedback/` - Capture Helpful/Not Helpful feedback from static pages (Legal, FAQ)

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

### Production Deployment

The project includes Heroku-ready configuration:

```bash
# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Collect static files
python manage.py collectstatic

# Start services (using Procfile)
gunicorn hb.wsgi:application
celery -A hb worker --loglevel=info
celery -A hb beat --loglevel=info
```

## 🗄️ Database Schema

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

Run the test suite:

```bash
# Run all tests
python manage.py test

# Run with coverage
coverage run --source='.' manage.py test
coverage report
```

## 📝 Management Commands

### Sample Data Generation

```bash
# Recommended for fresh dev environments
python manage.py create_sample_data --clean

# Custom counts
python manage.py create_sample_data --users 50 --listings 150 --orders 30
```

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
- [x] Real-time notifications (Email triggers and hourly Celery beat background services operational)
- [ ] API rate limiting dashboard

---

**Harbour Hub** - Connecting the Oil & Gas Industry 🌊⚙️
