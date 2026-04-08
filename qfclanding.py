from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn

app = FastAPI(title="QuantumForge Coin - Landing")

LANDING_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>QuantumForge Coin - QFC</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body { background: #0a0a1f; color: #e0ffe0; font-family: system-ui, sans-serif; }
        .hero { background: linear-gradient(135deg, #0a0a1f, #1a1a2e); position: relative; overflow: hidden; }
        .hero::before {
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0; bottom: 0;
            background: radial-gradient(circle at center, rgba(0,255,136,0.12) 0%, transparent 70%);
            pointer-events: none;
        }
        .glow-text {
            text-shadow: 0 0 30px #00ff88, 0 0 60px #00ff88, 0 0 90px rgba(0,255,136,0.5);
        }
        .coin {
            filter: drop-shadow(0 0 80px rgba(0,255,136,0.7));
            transition: transform 0.8s ease;
        }
        .coin:hover { transform: rotate(12deg) scale(1.08); }
        .card { background: #111827; border: 2px solid #00ff88; border-radius: 24px; padding: 40px; transition: all 0.3s; }
        .card:hover { transform: translateY(-8px); box-shadow: 0 0 40px rgba(0,255,136,0.4); }
        .accent { color: #00ff88; }
        .utility-point { transition: all 0.3s; }
        .utility-point:hover { transform: scale(1.05); }
    </style>
</head>
<body class="min-h-screen">
    <!-- HERO -->
    <div class="hero py-24 text-center relative">
        <div class="max-w-5xl mx-auto px-8">
            <img src="https://lh3.googleusercontent.com/d/1KL5twf6dD9waLSnfXFeJ2FurE5xwljqF" 
                 alt="QuantumForge Coin" 
                 class="coin mx-auto w-72 md:w-96 mb-12">
            
            <h1 class="text-7xl md:text-8xl font-bold glow-text mb-6 tracking-tighter">
                QUANTUMFORGE<br>COIN
            </h1>
            <p class="text-3xl md:text-4xl max-w-3xl mx-auto mb-12 text-emerald-100">
                The first post-quantum currency built for real-world use — with monthly basic income, unbreakable security, and intelligent growth.
            </p>
            
            <a href="http://127.0.0.1:8000" 
               class="inline-flex items-center gap-4 bg-emerald-500 hover:bg-emerald-600 text-black font-bold text-3xl px-16 py-8 rounded-3xl transition-all shadow-2xl">
                🚀 Launch Wallet Now
            </a>
        </div>
    </div>

    <!-- REAL UTILITY -->
    <div class="max-w-6xl mx-auto px-8 py-20">
        <h2 class="text-5xl font-bold text-center mb-4 accent">Real Utility. Real Purpose.</h2>
        <p class="text-center text-2xl max-w-2xl mx-auto mb-16 opacity-90">Unlike speculative tokens, QFC was designed from day one to be used daily by real people.</p>
        
        <div class="grid md:grid-cols-3 gap-8">
            <div class="card utility-point">
                <h3 class="text-2xl font-semibold mb-6 accent">💸 Everyday Payments</h3>
                <p class="text-lg">Send and receive QFC instantly for goods, services, bills, or peer-to-peer transfers. Simple QR scanning makes it easier than cash or cards.</p>
            </div>
            <div class="card utility-point">
                <h3 class="text-2xl font-semibold mb-6 accent">📈 Monthly Basic Income</h3>
                <p class="text-lg">Hold QFC and automatically receive proportional yield from the global treasury every 30 days — real passive income that rewards participation.</p>
            </div>
            <div class="card utility-point">
                <h3 class="text-2xl font-semibold mb-6 accent">🔒 Post-Quantum Security</h3>
                <p class="text-lg">The Phantom Jumper Key System morphs your private key with every block. Attacks have no fixed target — the most advanced security ever built into a currency.</p>
            </div>
        </div>
    </div>

    <!-- HOW IT WORKS -->
    <div class="max-w-4xl mx-auto px-8 py-16 bg-zinc-950">
        <h2 class="text-5xl font-bold text-center mb-12 accent">How It Works</h2>
        <div class="grid md:grid-cols-4 gap-8 text-center">
            <div class="space-y-4">
                <div class="text-6xl">1️⃣</div>
                <h4 class="font-semibold text-xl">Create Wallet</h4>
                <p class="opacity-75">Generate a unique seed + PIN in seconds. Fully self-custodial.</p>
            </div>
            <div class="space-y-4">
                <div class="text-6xl">2️⃣</div>
                <h4 class="font-semibold text-xl">Phantom Morphing</h4>
                <p class="opacity-75">Your key automatically morphs with every block — quantum-resistant security.</p>
            </div>
            <div class="space-y-4">
                <div class="text-6xl">3️⃣</div>
                <h4 class="font-semibold text-xl">Earn Monthly</h4>
                <p class="opacity-75">Hold ≥500 QFC and receive proportional yield from the treasury every 30 days.</p>
            </div>
            <div class="space-y-4">
                <div class="text-6xl">4️⃣</div>
                <h4 class="font-semibold text-xl">Send &amp; Receive</h4>
                <p class="opacity-75">Instant peer-to-peer transfers with built-in QR scanning.</p>
            </div>
        </div>
    </div>

    <!-- GET STARTED -->
    <div class="max-w-6xl mx-auto px-8 py-20 text-center">
        <div class="card max-w-2xl mx-auto">
            <h3 class="text-4xl font-bold mb-8 accent">Ready for the Future?</h3>
            <a href="http://127.0.0.1:8000" 
               class="inline-block bg-emerald-500 hover:bg-emerald-600 text-black font-bold text-3xl px-16 py-8 rounded-3xl transition-all">
                🚀 Launch Wallet Now
            </a>
            <p class="mt-10 text-sm opacity-70">Hard cap: 21 million QFC • Treasury starts with 10.5 million</p>
        </div>
    </div>

    <!-- FOOTER -->
    <div class="text-center py-12 border-t border-zinc-800 text-sm opacity-60">
        <p>Built with post-quantum hardening • Phantom Jumper Key System • Monthly Basic Income</p>
        <p class="mt-4">© 2026 Veu Now LLC • All Rights Reserved</p>
    </div>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def landing():
    return HTMLResponse(content=LANDING_HTML)

if __name__ == "__main__":
    print("\n🌐 QuantumForge Coin - Enhanced Landing Page with Strong Utility")
    print("Open in browser → http://127.0.0.1:8002")
    print("Press Ctrl+C to stop")
    uvicorn.run(app, host="127.0.0.1", port=8002)