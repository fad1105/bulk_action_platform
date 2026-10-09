
> Engineering standards for Django projects.
>
> This document defines how Claude should analyze, design, and implement changes in a Django codebase. The goal is consistency, maintainability, testability, and minimal review feedback.
>
> Unless the existing project clearly follows another architecture, prefer these conventions.

---

# Core Principles

Before writing code:

1. Search for existing implementations.
2. Reuse before creating new abstractions.
3. Follow the existing coding style.
4. Keep changes as small as possible.
5. Prefer consistency over cleverness.

Never introduce a new architectural pattern if the project already has one.

---

# Architecture

Unless the project already uses another pattern, follow a layered architecture.

```
HTTP Request
      │
      ▼
 View / ViewSet
      │
      ▼
 Service
      │
      ▼
 Repository
      │
      ▼
 Models
```

Responsibilities:

| Layer      | Responsibility                                              |
| ---------- | ----------------------------------------------------------- |
| View       | Parse request, authorize, validate serializer, call service |
| Service    | Business logic and orchestration                            |
| Repository | Database access                                             |
| Model      | Data schema and small helper methods                        |
| Serializer | Validation and serialization                                |
| DTO        | Internal data transfer                                      |

Dependency direction is always downward.

Views → Services → Repositories → Models

Never reverse this dependency.

---

# View Rules

Views should remain thin.

Views may:

* authenticate
* authorize
* validate request
* call one service
* return Response

Views should never:

* contain business logic
* query ORM directly
* coordinate multiple repositories
* call external APIs

Example:

```python
serializer.is_valid(raise_exception=True)

result = self.user_service.create_user(serializer.validated_data)

return Response(result)
```

---

# Service Rules

Services contain business logic.

A service should:

* orchestrate repositories
* call external integrations
* implement business rules
* manage transactions
* compose multiple services

A service should never:

* return Django Responses
* access request objects
* parse HTTP input
* contain raw ORM queries

Initialize dependencies in `__init__`.

Good:

```python
class UserService:
    def __init__(self):
        self.repository = UserRepository()
```

Avoid:

```python
def create():
    repo = UserRepository()
```

Prefer constructor dependency injection for collaborating services.

---

# Repository Rules

Repositories own all database access.

Every ORM query belongs inside a repository.

Bad

```python
User.objects.filter(...)
```

inside a Service.

Good

```python
UserRepository.get_active_users()
```

Repository methods should

* have descriptive names
* contain one query responsibility
* return models/querysets/DTOs
* avoid business decisions

Prefer

```python
.exists()

.count()

.values()

.only()

.defer()

select_related()

prefetch_related()
```

over unnecessary object loading.

---

# Model Rules

Models represent persistence.

Models should contain

* fields
* Meta
* indexes
* constraints
* small helper methods

Avoid

* external API calls
* repository calls
* business orchestration

Keep model methods deterministic.

---

# Serializer Rules

Serializers are responsible for

* validation
* serialization
* deserialization

Avoid

* business logic
* ORM queries
* external calls

Complex validation belongs in services.

---

# DTO Rules

Use dataclasses for internal communication.

```python
@dataclass(frozen=True)
class UserDTO:
    id: int
    email: str
```

Prefer DTOs over dictionaries when data crosses layer boundaries.

Keep DTOs reusable.

---

# Dependency Injection

Prefer constructor injection.

```python
class OrderService:
    def __init__(
        self,
        payment_service: PaymentService,
    ):
        self.payment_service = payment_service
```

Avoid creating collaborators repeatedly inside methods.

---

# Factory Pattern

When behavior varies by provider or strategy, use a Factory.

Avoid

```python
if provider == "stripe":
```

scattered across the codebase.

Instead

```python
PaymentFactory.get(provider)
```

---

# Business Logic

Business logic belongs only inside Services.

Avoid putting business rules inside

* serializers
* models
* views
* repositories

---

# Transactions

Transactions belong in services.

```python
@transaction.atomic
def create_order(...):
```

Repositories should not manage transactions.

---

# Error Handling

Use custom exceptions for domain failures.

```python
class OrderAlreadyPaid(Exception): ...
```

Catch only when recovery is possible.

Unexpected exceptions should

* be logged
* be reported
* be re-raised or converted into a domain failure

Never silently ignore exceptions.

---

# Logging

Use structured logging.

Prefer

```python
logger.info(
    "order_created",
    extra={
        "order_id": order.id,
    },
)
```

Avoid

```python
logger.info(f"Created order {order.id}")
```

Static messages improve searching and aggregation.

---

# Configuration

Never hardcode

* API keys
* URLs
* timeouts
* feature toggles

Use

* Django settings
* environment variables
* configuration objects

---

# Validation

Validate once.

Boundary validation

* serializers
* forms

Business validation

* services

Avoid duplicate validation.

---

# Performance

Avoid N+1 queries.

Use

```python
select_related()

prefetch_related()
```

Push filtering to the database.

Prefer

```python
.exists()

.count()
```

instead of loading objects.

Use

```python
bulk_create()

bulk_update()
```

when appropriate.

---

# Security

Never expose secrets.

Never trust client input.

Validate permissions before business logic.

Use

* CSRF protection where applicable
* Django permissions
* secure password hashing
* parameterized ORM queries

Never build raw SQL unless necessary.

---

# Migrations

Keep migrations focused.

When working on an unreleased feature, consider updating the existing migration instead of creating multiple incremental migrations.

Never edit historical migrations that are already deployed.

---

# Naming

Use descriptive names.

Examples

```
UserRepository

OrderService

PaymentFactory

UserDTO

PaymentStatus

CreateOrderSerializer
```

Avoid abbreviations unless they are well-known.

---

# Type Hints

Type annotate all public methods.

```python
def get_user(user_id: int) -> User:
```

Prefer explicit types.

---

# Docstrings

Public methods should include docstrings.

Example

```python
def create_order(order: OrderDTO) -> Order:
    """
    Create a new order.

    Args:
        order: Order information.

    Returns:
        Newly created Order.
    """
```

Use the project's preferred style (Google, NumPy, or reST) consistently.

---

# Testing

Prefer testing services.

Mock

* HTTP calls
* cloud storage
* queues
* email
* payment providers

Test

* happy paths
* validation failures
* edge cases
* exceptions

Tests should be deterministic.

Avoid unnecessary database usage.

---

# Code Style

Follow the project's formatter.

Typical choices include

* Ruff
* Black
* isort

Do not introduce a different formatter.

Respect existing import ordering.

---

# Before Adding New Code

Always check whether the project already has

* Service
* Repository
* Manager
* Factory
* Utility
* DTO
* Enum
* Base class

Reuse existing implementations whenever possible.

---

# Before Opening a PR

* Views remain thin.
* Business logic lives in services.
* ORM access stays in repositories.
* Validation occurs once.
* Types are complete.
* Logging is structured.
* Exceptions are meaningful.
* Tests cover the new behavior.
* Performance implications have been considered.
* Existing abstractions are reused.

---

# Claude Workflow

When asked to implement a feature:

1. Understand the existing architecture.
2. Search for similar implementations.
3. Reuse existing abstractions.
4. Make the smallest possible change.
5. Preserve existing style.
6. Keep layers separated.
7. Add tests if applicable.
8. Avoid introducing unnecessary abstractions.

When unsure:

* Prefer consistency over optimization.
* Prefer explicit code over clever code.
* Follow surrounding code rather than personal preference.
* If the repository has no established convention for a particular concern, state that clearly rather than inventing one.
