# Operation Zero — Project Instructions

## 1. Project Overview

Operation Zero is a multiplayer tactical extraction shooter developed using Unreal Engine 5.

The primary objective is to build a portfolio project demonstrating end-to-end multiplayer game architecture, including:

- Backend development
- Player authentication and profiles
- Persistent inventory and progression
- Party and lobby systems
- Matchmaking
- Dedicated game server management
- Multiplayer gameplay
- Cloud infrastructure and deployment

The project should demonstrate real engineering skills, maintainable architecture, and reliable multiplayer systems.

## 2. Technology Stack

### Game
- Unreal Engine 5
- C++
- Blueprints
- Unreal Engine replication
- Unreal Dedicated Servers

### Backend
- Python
- FastAPI
- MongoDB
- Redis
- REST APIs
- WebSockets

### Infrastructure
- Docker
- AWS
- GitHub Actions

Do not introduce additional technologies without explaining their purpose and trade-offs.

## 3. System Architecture and Responsibilities

### Backend Responsibilities

The Python backend owns persistent player and account data:

- Player accounts and authentication
- Player profiles
- Persistent inventory
- Player progression
- Party management
- Matchmaking
- Dedicated server registration and allocation
- Match result validation
- Reward settlement

### Unreal Dedicated Server Responsibilities

The dedicated server owns authoritative real-time gameplay:

- Player movement and gameplay state
- Weapons and shooting
- Damage and health during matches
- Loot spawning and pickup validation
- Match timers and objectives
- Extraction logic
- Temporary match state

### Unreal Client Responsibilities

The client handles:

- User interface
- Player input
- Presentation and animations
- Backend communication
- Connecting to dedicated servers
- Displaying player profiles and inventory

The client must never be trusted to determine persistent inventory ownership, rewards, or authoritative match results.

## 4. Communication Architecture

Use the appropriate communication mechanism for each responsibility:

- HTTPS/REST for backend request-response operations.
- WebSockets for real-time backend communication such as parties and lobby events.
- Unreal networking for real-time gameplay between clients and dedicated servers.
- Authenticated server-to-backend communication for server registration, ticket validation, and match result submission.

Do not route real-time gameplay operations through the Python backend.

## 5. Architecture Principles

1. Start with a modular monolith backend.
2. Avoid premature microservices.
3. Keep responsibilities clearly separated.
4. Use MongoDB for persistent data.
5. Use Redis for transient state and coordination where appropriate.
6. Design important operations to handle concurrent requests safely.
7. Use idempotency for operations that must not execute multiple times.
8. Apply authentication and authorization consistently.
9. Never trust client-submitted data for authoritative game outcomes.
10. Keep backend communication separate from gameplay networking.
11. Prefer simple, maintainable solutions over unnecessary abstractions.

## 6. Documentation and Contracts

The docs directory is the shared source of project knowledge.

Relevant documents will include:

- PROJECT_OVERVIEW.md
- SYSTEM_ARCHITECTURE.md
- BACKEND_ARCHITECTURE.md
- DATABASE_SCHEMA.md
- API_CONTRACTS.md
- WEBSOCKET_PROTOCOL.md
- GAME_SERVER_PROTOCOL.md

Rules:

1. Read relevant documentation before implementing a feature.
2. Never invent API endpoints, request formats, response formats, or WebSocket events.
3. Treat approved contracts as the source of truth.
4. FastAPI OpenAPI documentation should be the source of truth for REST API contracts.
5. Maintain explicit, versioned message schemas for WebSocket communication.
6. Identify documentation affected by every architectural or contract change.
7. Do not silently change approved contracts.
8. Explain breaking changes and their impact on other components.

Do not assume every document already exists. Create documents incrementally as the project develops.

## 7. Development Workflow

Work incrementally, one feature or milestone at a time.

Before implementation:

1. Inspect the existing repository and relevant source code.
2. Read the applicable CLAUDE.md instructions.
3. Read relevant architecture and contract documentation.
4. Understand existing implementation decisions.
5. Explain the proposed approach and affected components.
6. Identify assumptions, risks, and unresolved questions.

For significant architectural or contract changes, discuss the proposal before implementation.

After implementation:

1. Summarize the changes.
2. Explain important implementation decisions.
3. Report tests executed and their results.
4. Identify documentation that needs updating.
5. Identify dependencies or integration work required by other components.

## 8. Code Quality and Security

- Write maintainable, readable, well-structured code.
- Avoid unnecessary duplication.
- Handle errors and edge cases.
- Add tests for important business logic.
- Never hardcode credentials or secrets.
- Use environment variables for configuration.
- Follow secure authentication and authorization practices.
- Do not introduce unnecessary dependencies.

## 9. AI Collaboration Rules

Act as a senior software engineer and technical collaborator.

Do not blindly agree with proposed designs.

When reviewing architecture or implementation:

- Identify potential weaknesses.
- Explain alternative approaches.
- Consider security, concurrency, scalability, and maintainability.
- Distinguish confirmed decisions from suggestions.
- Ask questions when requirements are ambiguous.
- Do not make major architectural assumptions without discussing them.

The developer is responsible for understanding and approving important architectural decisions.