# Contributing to Estate Steward

Thank you for your interest in contributing to Estate Steward! We welcome community contributions to help make this local-first probate mediation platform even better.

## How to Contribute

1. **Fork the Repository**: Start by forking the repository to your own GitHub account.
2. **Clone Locally**: Clone your fork to your local machine.
3. **Create a Branch**: Create a new branch for your feature or bug fix (`git checkout -b feature/your-feature-name`).
4. **Make Changes**: Implement your changes. Please ensure you adhere to the coding standards used in the project.
5. **Test Your Changes**: Verify that your changes work as expected and don't break existing functionality. Run the backend tests and ensure the frontend builds successfully.
6. **Commit**: Commit your changes with clear, descriptive commit messages.
7. **Push**: Push your branch to your fork on GitHub.
8. **Submit a Pull Request**: Open a pull request against the `main` branch of the original repository. Provide a detailed description of what your PR accomplishes.

## Development Setup

The project uses Docker Compose for local development.

### Requirements
- Docker and Docker Compose
- Node.js (for frontend development outside of Docker, optional)
- Python 3.11+ (for backend development outside of Docker, optional)

### Running Locally
1. Copy `.env.example` to `.env`.
2. Run `docker compose up --build`.
3. The frontend is accessible at `http://localhost`.
4. The backend API is accessible at `http://localhost/api/docs`.

## Code Style

### Frontend (React/Vite)
- We use ESLint for code formatting. Please ensure your code passes `npm run lint`.
- Use functional components and hooks.
- Styling uses vanilla CSS (avoid adding heavy UI libraries unless absolutely necessary).

### Backend (Python/FastAPI)
- Please use type hints for all functions.
- Run tests before submitting PRs.

## Reporting Bugs and Requesting Features
If you find a bug or have an idea for a feature, please open an issue in the GitHub issue tracker. Provide as much context and detail as possible.

We look forward to your contributions!
