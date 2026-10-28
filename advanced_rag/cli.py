import argparse
from .app import RAGApp

def main(argv=None):
    p=argparse.ArgumentParser(description="Local-first grounded RAG")
    p.add_argument("--knowledge",default="knowledge"); p.add_argument("--data",default=".rag_data"); p.add_argument("--query"); p.add_argument("--serve",action="store_true"); p.add_argument("--ui",action="store_true"); p.add_argument("--force",action="store_true")
    args=p.parse_args(argv); from .config import Settings
    s=Settings.from_env(knowledge_dir=args.knowledge,data_dir=args.data); app=RAGApp(s); print(app.ingest(force=args.force))
    if args.query: print(app.query(args.query))
    elif args.serve:
        import uvicorn
        from .api import create_app
        uvicorn.run(create_app(app),host=s.host,port=s.port)
    elif args.ui:
        from .ui import run; run(app)
    return 0
