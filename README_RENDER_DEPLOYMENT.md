# TABLEAU2PBI Render Deployment - v10.4.0

This package is Render-ready and verified with:
- Backend: FastAPI/Uvicorn, Python 3.12.8
- Frontend: React 18 + Vite 5 + TypeScript 5, Node 20.19.0

## Deploy
1. Push this folder to GitHub. `render.yaml` must be at repo root.
2. Render > New > Blueprint > select the repository.
3. Deploy the Blueprint.
4. Test backend: `https://tableau2pbi-api.onrender.com/api/health`
5. Test UI: `https://tableau2pbi-ui.onrender.com`

## Important
If frontend still fails after previous attempts, use Render > tableau2pbi-ui > Manual Deploy > Clear build cache & deploy.
