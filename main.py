from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "Arey waah Shan! Ethrix-Forge ka Backend Zinda ho gaya! 🚀"}