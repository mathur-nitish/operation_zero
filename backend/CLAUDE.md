# Operation Zero — Backend Development Instructions

## 1. Backend Overview

The backend is responsible for persistent player data, authentication, party management, matchmaking, and dedicated game server orchestration.

The backend is developed in Python using FastAPI.

Read the root CLAUDE.md before making backend changes.
For testing, choose mongodb, which will be setup locally on the pc.

## 2. Technology Stack

- Python
- FastAPI
- MongoDB
- Redis
- WebSockets
- Pydantic
- Pytest
- Docker

Prefer asynchronous implementations where appropriate.

Use maintained libraries and avoid introducing unnecessary dependencies.

## 3. Backend Responsibilities

The backend will progressively implement the following modules:

### Authentication
- Player registration
- Login
- Token generation and validation
- Authentication middleware
- Authorization

### Player Management
- Player profiles
- Account information
- Player progression

### Inventory
- Item definitions
- Player-owned inventory
- Equipment management
- Inventory updates
- Persistent inventory transactions

### Party and Lobby
- Party creation
- Party invitations
- Joining and leaving parties
- Party leadership
- Ready state
- Real-time party events

### Matchmaking
- Matchmaking queues
- Player and party matchmaking
- Match creation
- Match assignment

### Dedicated Server Management
- Server registration
- Server heartbeat
- Server availability
- Server allocation
- Connection ticket generation and validation

### Match Results
- Match result submission
- Result validation
- Reward calculation
- Idempotent reward settlement

Do not implement all modules at once. Follow the approved development milestones.

## 4. Backend Architecture Rules

Keep the backend modular and maintainable.

Separate responsibilities such as:

- API routes
- Request and response schemas
- Business logic and services
- Database access and repositories
- Authentication and authorization
- WebSocket connection management
- Configuration
- Tests

Avoid putting business logic directly inside API route handlers.

Do not introduce microservices unless there is a clearly justified architectural requirement.

## 5. Database Rules

### MongoDB

Use MongoDB for persistent information, including:

- Accounts
- Player profiles
- Inventory
- Item definitions
- Progression
- Match history
- Persistent transactions

Database design must consider:

- Document relationships
- Query patterns
- Indexes
- Data consistency
- Concurrent updates
- Atomic operations
- Transaction requirements

Do not create collections or database schemas without considering their actual access patterns.

### Redis

Use Redis for suitable transient or coordination-related data, including:

- Online player state
- Active party state
- Matchmaking queues
- Server registry
- Temporary session information
- Short-lived tickets and coordination data

Do not use Redis as a replacement for persistent player data.

## 6. API and WebSocket Rules

### REST APIs

- Use Pydantic request and response models.
- Use consistent response and error structures.
- Apply authentication and authorization where required.
- Keep API endpoints versionable.
- Maintain FastAPI OpenAPI documentation.

FastAPI OpenAPI should remain the source of truth for REST API contracts.

### WebSockets

- Authenticate WebSocket connections.
- Validate incoming messages.
- Use a consistent message envelope.
- Handle disconnects and reconnects.
- Handle duplicate messages safely where required.
- Keep WebSocket event definitions documented.

Never silently change an existing API or WebSocket contract.

Identify the impact on Unreal integration before changing shared contracts.

## 7. Security and Reliability

1. Never trust the Unreal client to submit authoritative match results or reward decisions.
2. Validate dedicated server requests using authenticated server credentials or equivalent secure mechanisms.
3. Enforce authorization on player-owned resources.
4. Prevent players from modifying another player's inventory or profile.
5. Make important operations idempotent.
6. Handle concurrent requests and race conditions.
7. Validate all external input.
8. Protect secrets using environment variables and secure configuration.
9. Avoid logging passwords, tokens, or sensitive credentials.
10. Implement sensible timeouts and error handling.

## 8. Testing

Use Pytest for automated tests.

Prioritize tests for:

- Authentication and authorization
- Player profile access
- Inventory updates
- Concurrent inventory operations
- Party membership rules
- Matchmaking
- Server allocation
- Connection ticket validation
- Duplicate match result submissions
- Reward settlement

Do not claim a feature is working without identifying the tests executed and their results.

## 9. Documentation Rules

Before implementing a feature, read the relevant documentation from the root docs directory.

Update the relevant documentation when changing:

- Database collections or schemas
- API endpoints
- Request and response models
- WebSocket messages
- Authentication flows
- Matchmaking behavior
- Dedicated server communication
- Important architectural decisions

Do not duplicate generated OpenAPI documentation manually.

Keep approved database and communication decisions documented.

## 10. Development Workflow

Before coding:

1. Inspect the existing backend structure.
2. Read the root CLAUDE.md.
3. Read relevant architecture and database documents.
4. Explain the proposed implementation.
5. Identify affected files and modules.
6. Identify testing requirements.

After coding:

1. Summarize implemented functionality.
2. List important files created or modified.
3. Explain important decisions.
4. Run relevant tests.
5. Report test results.
6. Update affected documentation.
7. Identify any required Unreal integration changes.

Work incrementally. Do not implement unrelated features or rewrite existing code without justification.