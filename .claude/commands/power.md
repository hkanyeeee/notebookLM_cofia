---
description: Full-stack development workflow combining Vue frontend, FastAPI backend specialists with deep planning
argument-hint: [feature or task description]
---

# Full-Stack Power Development Workflow

Execute a comprehensive three-phase development process integrating frontend, backend, and strategic planning expertise.

## Phase 1: Deep Planning & Architecture Analysis

Use the **deep-planner** subagent for comprehensive analysis:

/agents @deep-planner

Please analyze the following development task: $ARGUMENTS

## Phase 2: Coordinated Full-Stack Development

Based on the deep-planner analysis, proceed with coordinated development, **must use sub agents**:

### Backend Development with FastAPI Specialist

/agents @python-fastapi-developer

Based on the planning analysis above, implement the backend requirements for: $ARGUMENTS

### Frontend Development with Vue.js Specialist  

/agents @vue-developer

Based on the planning analysis and backend implementation above, implement the frontend requirements for: $ARGUMENTS

*Note: Ensure API compatibility and streaming response format alignment between backend and frontend phases.*

## Phase 3: Integration & Optimization

After completing development, perform integration and optimization:

1. **API Integration Testing**
   - Frontend-backend interface coordination
   - Streaming data rendering validation
   - User interaction and error handling verification

2. **Performance Optimization**
   - Frontend: Component rendering optimization, code splitting
   - Backend: Database query optimization, async processing
   - Overall: Reduce API calls, implement caching strategies

3. **Code Quality Assurance**
   - TypeScript type safety validation
   - Error handling enhancement
   - Code standards and documentation

---

## Workflow Details

### Phase 1 - Deep Planning (@deep-planner)
The **deep-planner** subagent will:
- Conduct comprehensive project structure analysis
- Create detailed phased execution plans
- Identify risks and mitigation strategies
- Generate planning documentation if needed

### Phase 2 - Specialist Development
**Backend Specialist** (@python-fastapi-developer) handles:
- RESTful API design and implementation
- Database operations and vector processing
- Streaming responses (OpenAI-compatible format)
- Async programming and performance optimization

**Frontend Specialist** (@vue-developer) handles:
- Vue 3.5 component development with Composition API
- Pinia state management and reactive updates
- Streaming render fixes and UI interactions
- TypeScript integration and Element Plus styling

### Phase 3 - Integration & Quality
Main process coordinates:
- Integration between frontend and backend implementations
- Streaming update compatibility validation
- Overall system functionality verification
- Performance optimization and maintainability enhancement

## Technical Guidelines

### Key Technical Points
- **Streaming Updates**: Use array index replacement instead of direct object property modification
- **State Management**: Update through Pinia proxy objects, avoid direct original object modification
- **API Compatibility**: Follow OpenAI format, prioritize `reasoning_content` then `content`

### Tech Stack Requirements
- **Frontend**: Vue 3.5 + TypeScript + Pinia + Element Plus + Tailwind CSS
- **Backend**: FastAPI + SQLAlchemy + Qdrant + uvicorn
- **Integration**: Ensure code style consistency and type safety

## Usage Examples

```bash
/power "Add real-time chat functionality with message history"
/power "Implement document upload and vector search feature"  
/power "Create user authentication system with role management"
/power "Add streaming response visualization with progress indicators"
```
