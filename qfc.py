from fastapi import FastAPI, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
import uvicorn
import os
import json
import time
import hashlib
import random
import asyncio
import stripe
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Dict, List

app = FastAPI(title="QuantumForge Coin")

# ==================== ENVIRONMENT VARIABLES WITH LOCAL FALLBACK ====================
STRIPE_API_KEY = os.getenv("STRIPE_API_KEY", "sk_test_51TJIWDCLs3QhIrfWzBIuNbfBeIJZ8EP5ehWKhecN0OAeHlKkhYo25jmzabUiXv6QNRztaQ0PlOMJFPtywsWhnS1l00AHWqQEq9")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_oUbfUZw9XvkoAYzThbcciY5RUtijqN6D")
TREASURY_PASSWORD = os.getenv("TREASURY_PASSWORD", "79369943077973")

stripe.api_key = STRIPE_API_KEY

# ==================== CONFIG ====================
TOTAL_SUPPLY_CAP = 21_000_000
GENESIS_TREASURY_AMOUNT = 10_500_000.0
INITIAL_TREASURY_USD = 50_000.0
INITIAL_BLOCK_REWARD = 25.0
HALVING_INTERVAL = 500
MIN_YIELD_BALANCE = 500.0
YIELD_INTERVAL_SECONDS = 2_592_000
POOL_BONUS_THRESHOLD = 10.0
GAS_FEE_PERCENT = 0.01

TREASURY_PATH = "/op-console-9x7k2m4p8q"

my_addr = "d0ff5d049bcc4ecf176b7523901a1f4c0a429d98285966ca1919ceb0291b2638"
treasury_balance = GENESIS_TREASURY_AMOUNT
treasury_usd = INITIAL_TREASURY_USD
holder_reward_pool = 0.0
chain_height = 235
current_block_reward = INITIAL_BLOCK_REWARD
transactions: List[Dict] = []
wallet_balances: Dict[str, float] = {my_addr: 500110.077680}
wallet_usd_balances: Dict[str, float] = {my_addr: 100.0}

LAST_YIELD_TIME = time.time() - 60
LAST_AUTO_MINE_TIME = time.time() - 600
recent_buy_volume = 0.0
radar_history: List[Dict] = []

TREASURY_MINING_SHARE = 0.7
HOLDER_MINING_SHARE = 0.3
MIN_YIELD_RATE = 0.001
MAX_YIELD_RATE = 0.005
TREASURY_MAX_MONTHLY_PCT = 0.005

def derive_address(seed: str, pin: str) -> str:
    return hashlib.sha3_256(f"{seed}:{pin}".encode()).hexdigest()

def get_morphed_key(seed: str, pin: str, height: int) -> str:
    return hashlib.sha3_512(f"{seed}:{pin}:{height}".encode()).hexdigest()[:64]

def calculate_mining_interval():
    supply_ratio = treasury_balance / TOTAL_SUPPLY_CAP
    demand_factor = min(1.0, recent_buy_volume / 10000)
    scarcity_factor = 1.0 - supply_ratio
    interval_seconds = 1800 - (demand_factor * 900) + (scarcity_factor * 900)
    return max(600, min(3600, int(interval_seconds)))

def get_adaptive_min_reserve():
    """Intelligent adaptive liquidity reserve that grows with the system"""
    live_price = min(0.50, 0.01 * (1 + (1 - treasury_balance / TOTAL_SUPPLY_CAP) * 1.5))
    base = 250.0
    treasury_pct = treasury_usd * 0.07
    circulation_ratio = (TOTAL_SUPPLY_CAP - treasury_balance) / TOTAL_SUPPLY_CAP
    circulation_protection = treasury_usd * circulation_ratio * 0.03
    return max(base, treasury_pct + circulation_protection)

def load_state():
    global treasury_balance, treasury_usd, chain_height, holder_reward_pool, current_block_reward, recent_buy_volume, LAST_YIELD_TIME, LAST_AUTO_MINE_TIME, radar_history
    if os.path.exists("state.json"):
        try:
            with open("state.json") as f:
                data = json.load(f)
                treasury_balance = data.get("treasury_balance", treasury_balance)
                treasury_usd = data.get("treasury_usd", treasury_usd)
                chain_height = data.get("chain_height", chain_height)
                holder_reward_pool = data.get("holder_reward_pool", holder_reward_pool)
                current_block_reward = data.get("current_block_reward", current_block_reward)
                recent_buy_volume = data.get("recent_buy_volume", recent_buy_volume)
                LAST_YIELD_TIME = data.get("last_yield_time", LAST_YIELD_TIME)
                LAST_AUTO_MINE_TIME = data.get("last_auto_mine_time", LAST_AUTO_MINE_TIME)
                radar_history = data.get("radar_history", [])
                transactions.clear()
                transactions.extend(data.get("transactions", []))
                wallet_balances.update(data.get("wallet_balances", {}))
                wallet_usd_balances.update(data.get("wallet_usd_balances", {}))
        except Exception as e:
            print(f"[LOAD STATE ERROR] {e}")
    else:
        save_state()

def save_state():
    try:
        with open("state.json", "w") as f:
            json.dump({
                "treasury_balance": round(treasury_balance, 6),
                "treasury_usd": round(treasury_usd, 2),
                "chain_height": chain_height,
                "holder_reward_pool": round(holder_reward_pool, 6),
                "current_block_reward": current_block_reward,
                "recent_buy_volume": recent_buy_volume,
                "last_yield_time": LAST_YIELD_TIME,
                "last_auto_mine_time": LAST_AUTO_MINE_TIME,
                "radar_history": radar_history[-800:],
                "transactions": transactions[-100:],
                "wallet_balances": wallet_balances,
                "wallet_usd_balances": wallet_usd_balances
            }, f, indent=2)
    except Exception as e:
        print(f"[SAVE STATE ERROR] {e}")

load_state()

# ====================== AUTO TASKS ======================
async def auto_yield_task():
    global treasury_balance, LAST_YIELD_TIME
    while True:
        await asyncio.sleep(YIELD_INTERVAL_SECONDS)
        if time.time() - LAST_YIELD_TIME < 30: continue
        if treasury_balance < 1000: continue
        live_price = min(0.50, 0.01 * (1 + (1 - treasury_balance / TOTAL_SUPPLY_CAP) * 1.5))
        eligible = {addr: bal for addr, bal in wallet_balances.items() if bal >= MIN_YIELD_BALANCE}
        if not eligible:
            LAST_YIELD_TIME = time.time()
            continue
        total_eligible = sum(eligible.values())
        dynamic_rate = MIN_YIELD_RATE + (MAX_YIELD_RATE - MIN_YIELD_RATE) * (1 - treasury_balance / TOTAL_SUPPLY_CAP)
        monthly_pool = treasury_balance * min(dynamic_rate, TREASURY_MAX_MONTHLY_PCT)
        for addr, bal in eligible.items():
            reward = (bal / total_eligible) * monthly_pool
            wallet_balances[addr] = wallet_balances.get(addr, 0) + reward
            usd_equiv = round(reward * live_price, 2)
            transactions.append({"type": "monthly_yield", "amount": round(reward, 6), "usd_value": usd_equiv, "time": time.strftime("%Y-%m-%d %H:%M"), "to": addr})
        treasury_balance -= monthly_pool
        LAST_YIELD_TIME = time.time()
        save_state()

async def auto_pool_bonus_task():
    global holder_reward_pool
    while True:
        await asyncio.sleep(60)
        if holder_reward_pool < POOL_BONUS_THRESHOLD: continue
        eligible = [addr for addr, bal in wallet_balances.items() if bal >= MIN_YIELD_BALANCE]
        if eligible:
            share = holder_reward_pool / len(eligible)
            for addr in eligible:
                wallet_balances[addr] = wallet_balances.get(addr, 0) + share
                transactions.append({"type": "pool_bonus", "amount": round(share, 6), "time": time.strftime("%Y-%m-%d %H:%M"), "to": addr})
            holder_reward_pool = 0.0
            save_state()

async def perform_mine():
    global chain_height, holder_reward_pool, current_block_reward, treasury_balance, LAST_AUTO_MINE_TIME, recent_buy_volume
    chain_height += 1
    treasury_share = current_block_reward * TREASURY_MINING_SHARE
    holder_share = current_block_reward * HOLDER_MINING_SHARE
    treasury_balance += treasury_share
    holder_reward_pool += holder_share
    if chain_height % HALVING_INTERVAL == 0:
        current_block_reward = max(0.000001, current_block_reward / 2)
    LAST_AUTO_MINE_TIME = time.time()
    recent_buy_volume = 0.0
    transactions.append({"type": "mined", "amount": current_block_reward, "time": time.strftime("%Y-%m-%d %H:%M"), "to": "Treasury + Holder Pool"})
    save_state()
    print(f"✅ AUTO-MINE FIRED — Block {chain_height}")

async def auto_mine_task():
    while True:
        await asyncio.sleep(60)
        if time.time() - LAST_AUTO_MINE_TIME >= calculate_mining_interval():
            await perform_mine()

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield_task = asyncio.create_task(auto_yield_task())
    pool_task = asyncio.create_task(auto_pool_bonus_task())
    mine_task = asyncio.create_task(auto_mine_task())
    yield
    yield_task.cancel()
    pool_task.cancel()
    mine_task.cancel()

app = FastAPI(title="QuantumForge Coin", lifespan=lifespan)

# ====================== BEAUTIFUL MOBILE-FRIENDLY MARKETING LANDING PAGE ======================
@app.get("/", response_class=HTMLResponse)
async def landing():
    html = """<!DOCTYPE html>
<html>
<head>
    <title>QuantumForge Coin</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body { background: #0a0a1f; color: #e0ffe0; font-family: system-ui, sans-serif; }
        .hero { background: linear-gradient(135deg, #0a0a1f, #1a1a2e); }
        .glow { text-shadow: 0 0 60px #00ff88, 0 0 100px #00ff88; }
        .card { transition: all 0.3s ease; }
        .card:hover { transform: translateY(-4px); box-shadow: 0 20px 25px -5px rgb(0 255 136 / 0.2); }
    </style>
</head>
<body class="min-h-screen">
    <div class="hero py-12 md:py-20 text-center">
        <div class="max-w-4xl mx-auto px-4 md:px-6">
            <img src="https://lh3.googleusercontent.com/d/1KL5twf6dD9waLSnfXFeJ2FurE5xwljqF" alt="QFC" class="mx-auto w-48 md:w-64 mb-8">
            <h1 class="text-5xl md:text-6xl lg:text-7xl font-bold glow mb-4">QUANTUMFORGE COIN</h1>
            <p class="text-xl md:text-2xl mb-12 max-w-2xl mx-auto">The first post-quantum currency built for real-world use — with monthly basic income, unbreakable security, and intelligent growth.</p>
            <a href="/wallet" class="inline-block bg-emerald-500 hover:bg-emerald-600 text-black font-bold text-2xl px-10 md:px-12 py-6 rounded-3xl transition-all">Launch Wallet Now</a>
        </div>
    </div>

    <div class="max-w-6xl mx-auto px-4 md:px-6 py-12 md:py-16">
        <div class="grid grid-cols-1 md:grid-cols-3 gap-8">
            <div class="card bg-zinc-900 p-8 rounded-3xl text-center">
                <h3 class="text-emerald-400 text-xl mb-4">Everyday Payments</h3>
                <p>Send and receive QFC instantly for goods, services, bills, or peer-to-peer transfers. Simple QR scanning makes it easier than cash or cards.</p>
            </div>
            <div class="card bg-zinc-900 p-8 rounded-3xl text-center">
                <h3 class="text-emerald-400 text-xl mb-4">Monthly Basic Income</h3>
                <p>Hold QFC and automatically receive proportional yield from the global treasury every 30 days — real passive income that rewards participation.</p>
            </div>
            <div class="card bg-zinc-900 p-8 rounded-3xl text-center">
                <h3 class="text-emerald-400 text-xl mb-4">Post-Quantum Security</h3>
                <p>The Phantom Jumper Key system morphs your private key with every block. Attacks have no fixed target — the most advanced security ever built into a currency.</p>
            </div>
        </div>

        <div class="mt-16 md:mt-20 text-center">
            <h2 class="text-3xl md:text-4xl font-bold mb-8">How It Works</h2>
            <div class="grid grid-cols-1 md:grid-cols-4 gap-8 text-center">
                <div>
                    <div class="text-5xl font-bold text-emerald-400 mb-2">1</div>
                    <p class="font-bold">Create Wallet</p>
                    <p class="text-sm opacity-70">Generate a unique seed + PIN to be secure. Fully self-custodial.</p>
                </div>
                <div>
                    <div class="text-5xl font-bold text-emerald-400 mb-2">2</div>
                    <p class="font-bold">Phantom Morphing</p>
                    <p class="text-sm opacity-70">Your key morphs with every block — quantum-resistant security.</p>
                </div>
                <div>
                    <div class="text-5xl font-bold text-emerald-400 mb-2">3</div>
                    <p class="font-bold">Earn Monthly</p>
                    <p class="text-sm opacity-70">Hold QFC and receive basic income from the treasury every 30 days.</p>
                </div>
                <div>
                    <div class="text-5xl font-bold text-emerald-400 mb-2">4</div>
                    <p class="font-bold">Send & Receive</p>
                    <p class="text-sm opacity-70">Instant peer-to-peer transfers with built-in QR scanning.</p>
                </div>
            </div>
        </div>

        <div class="mt-16 md:mt-20 text-center bg-zinc-900 rounded-3xl p-8 md:p-12">
            <h2 class="text-3xl md:text-4xl font-bold mb-4">Ready for the Future?</h2>
            <a href="/wallet" class="inline-block bg-emerald-500 hover:bg-emerald-600 text-black font-bold text-2xl px-10 md:px-12 py-6 rounded-3xl transition-all">Launch Wallet Now</a>
            <p class="text-sm mt-6 opacity-70">Hard cap: 21 million QFC • Treasury starts with 10.5 million</p>
        </div>
    </div>

    <footer class="text-center py-12 text-xs opacity-50">
        Built with post-quantum technology • Phantom Jumper Key System • Monthly Basic Income
    </footer>
</body>
</html>
    """
    return HTMLResponse(html)

# ====================== FULL WALLET HTML — MOBILE OPTIMIZED ======================
@app.get("/wallet", response_class=HTMLResponse)
async def wallet():
    html = """<!DOCTYPE html>
<html>
<head>
    <title>QuantumForge Wallet</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/html5-qrcode@2.3.8/html5-qrcode.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { background: #0a0a1f; color: #e0ffe0; font-family: system-ui, sans-serif; }
        .hero { background: linear-gradient(135deg, #0a0a1f, #1a1a2e); position: relative; overflow: hidden; }
        .hero::before { content: ''; position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: radial-gradient(circle at center, rgba(0,255,136,0.12) 0%, transparent 70%); pointer-events: none; }
        .glow-text { text-shadow: 0 0 30px #00ff88, 0 0 60px #00ff88, 0 0 90px rgba(0,255,136,0.6); }
        .coin { filter: drop-shadow(0 0 80px rgba(0,255,136,0.8)); transition: transform 0.8s ease; }
        .coin:hover { transform: rotate(8deg) scale(1.06); }
        .card { background: #111827; border: 2px solid #00ff88; border-radius: 24px; padding: 24px; margin-bottom: 24px; }
        .accent { color: #00ff88; }
        .keybox { font-family: monospace; background: #1a1a2e; padding: 16px; border-radius: 12px; word-break: break-all; font-size: 13px; }
        .tx-item { background: #1a2338; padding: 14px; border-radius: 12px; margin-bottom: 8px; cursor: pointer; }
        .tx-item:hover { background: #25314f; }
        .copy-addr { color: #00ff88; text-decoration: underline; cursor: pointer; }
        .range-btn { padding: 6px 12px; margin: 0 4px; border-radius: 9999px; background: #1a2338; color: #e0ffe0; cursor: pointer; font-size: 14px; }
        .range-btn.active { background: #00ff88; color: #111827; font-weight: bold; }
        .success-toast { animation: popIn 0.4s ease; }
        @keyframes popIn { from { transform: scale(0.8); opacity: 0; } to { transform: scale(1); opacity: 1; } }
    </style>
</head>
<body class="p-4 md:p-8 max-w-5xl mx-auto">
    <div id="entry_hero" class="hero py-12 md:py-20 text-center rounded-3xl mb-8">
        <div class="max-w-4xl mx-auto px-4 md:px-8">
            <img src="https://lh3.googleusercontent.com/d/1KL5twf6dD9waLSnfXFeJ2FurE5xwljqF" alt="QuantumForge Coin" class="coin mx-auto w-56 md:w-72 lg:w-96 mb-8">
            <h1 class="text-4xl md:text-5xl lg:text-6xl font-bold glow-text mb-4">QuantumForge Wallet</h1>
            <p class="text-lg md:text-2xl mb-10 md:mb-12 opacity-90">Post-quantum security with monthly basic income from the treasury</p>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4 max-w-md mx-auto">
                <button onclick="createNewWallet()" class="py-7 bg-emerald-500 hover:bg-emerald-600 text-black font-bold rounded-3xl text-2xl transition-all">Create New Wallet</button>
                <button onclick="showRecover()" class="py-7 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-3xl text-2xl transition-all">Recover Existing Wallet</button>
            </div>
        </div>
    </div>

    <div id="new_wallet_modal" class="hidden fixed inset-0 bg-black/90 flex items-center justify-center z-50">
        <div class="card max-w-lg w-full mx-4">
            <h2 class="accent text-2xl mb-6 text-center">⚠️ STORE THIS SECURELY OFFLINE</h2>
            <div class="bg-zinc-900 p-6 rounded-3xl mb-6 space-y-4">
                <div><p class="font-mono text-sm mb-1">Seed Phrase:</p><p id="modal_seed" class="font-mono text-base"></p></div>
                <div><p class="font-mono text-sm mb-1">PIN:</p><p id="modal_pin" class="font-mono text-base"></p></div>
                <div><p class="font-mono text-sm mb-1">Wallet Address:</p><p id="modal_addr" class="font-mono text-sm break-all"></p></div>
            </div>
            <p class="text-sm opacity-80 mb-6 text-center">This is your only way to recover the wallet. Store it in a secure offline location (metal plate, encrypted drive, or safe). Never share it or store it digitally in an unsecured way.</p>
            <label class="flex items-center gap-3 mb-6 cursor-pointer">
                <input type="checkbox" id="confirm_written" class="w-6 h-6 accent" onchange="checkConfirm()">
                <span class="text-lg">I have securely stored this information offline</span>
            </label>
            <button onclick="confirmNewWallet()" id="confirm_btn" disabled class="w-full py-6 bg-emerald-500 hover:bg-emerald-600 text-black font-bold rounded-3xl text-xl">I have secured it — Open Wallet</button>
        </div>
    </div>

    <div id="recover_modal" class="hidden fixed inset-0 bg-black/90 flex items-center justify-center z-50">
        <div class="card max-w-md w-full mx-4">
            <h2 class="accent text-2xl mb-6 text-center">Recover Wallet</h2>
            <input id="recover_seed" placeholder="12-word seed phrase" class="w-full bg-zinc-900 px-6 py-5 rounded-2xl mb-4 font-mono text-sm">
            <input id="recover_pin" placeholder="6-digit PIN" maxlength="6" class="w-full bg-zinc-900 px-6 py-5 rounded-2xl mb-6 font-mono text-sm">
            <button onclick="recoverWallet()" class="w-full py-6 bg-emerald-500 hover:bg-emerald-600 text-black font-bold rounded-3xl text-xl">Recover Wallet</button>
            <button onclick="hideRecover()" class="mt-4 w-full py-4 text-zinc-400">Cancel</button>
        </div>
    </div>

    <div id="wallet_content" class="hidden space-y-8">
        <div class="card flex flex-col md:flex-row justify-between items-start gap-6">
            <div class="flex-1">
                <p class="opacity-70 text-sm">Your Balance</p>
                <div id="balance" class="text-5xl md:text-6xl font-bold accent">0.000000</div>
                <p class="text-2xl md:text-3xl">QFC</p>
                <div id="qfc_value" class="text-xl md:text-2xl text-amber-400 mt-1">Cash Value: $0.00</div>
                <div id="usd_balance" class="text-2xl md:text-3xl text-emerald-400 mt-3">$0.00 CASH</div>
            </div>
            <div class="flex flex-col gap-3 pt-2 w-full md:w-auto">
                <button onclick="manualRefresh()" class="px-8 py-4 bg-zinc-700 hover:bg-zinc-600 rounded-2xl font-bold flex items-center gap-2 justify-center">🔄 Refresh</button>
                <button onclick="exportWallet()" class="px-8 py-4 bg-zinc-700 hover:bg-zinc-600 rounded-2xl font-bold flex items-center gap-2 justify-center">📤 Export Wallet</button>
                <button onclick="addFunds()" class="px-8 py-4 bg-emerald-600 hover:bg-emerald-700 text-white rounded-2xl font-bold flex items-center gap-2 justify-center">💵 Add Funds</button>
                <button onclick="withdrawFunds()" class="px-8 py-4 bg-amber-600 hover:bg-amber-700 text-white rounded-2xl font-bold flex items-center gap-2 justify-center">🏦 Withdraw</button>
            </div>
        </div>

        <div class="card">
            <h3 class="accent text-2xl mb-4">Live QFC Price (USD)</h3>
            <div id="wallet_live_price" class="text-5xl md:text-6xl font-bold accent mb-4">$0.01</div>
            <canvas id="walletRadarChart" height="180"></canvas>
            <div class="flex justify-center mt-4 flex-wrap gap-2">
                <span onclick="setRange(1)" class="range-btn" id="btn-1">1h</span>
                <span onclick="setRange(24)" class="range-btn active" id="btn-24">24h</span>
                <span onclick="setRange(168)" class="range-btn" id="btn-168">7d</span>
                <span onclick="setRange(720)" class="range-btn" id="btn-720">30d</span>
                <span onclick="setRange(0)" class="range-btn" id="btn-0">All</span>
            </div>
        </div>

        <div class="card">
            <h3 class="accent mb-4">Buy QFC from Treasury <span id="live_price_display" class="text-sm font-normal opacity-70">( $0.01 )</span></h3>
            <input id="buy_usd" type="number" step="0.01" placeholder="Enter USD Amount (e.g. 10)" class="w-full bg-zinc-900 px-6 py-5 rounded-2xl text-xl mb-3" oninput="updateBuyPreview()">
            <div id="buy_preview" class="text-emerald-400 text-xl font-bold mb-4">You will receive: 0.000000 QFC</div>
            <div id="buy_gas" class="text-amber-400 text-sm">1% gas fee → Treasury Vault</div>
            <button onclick="buyQFC()" class="w-full py-6 bg-emerald-500 hover:bg-emerald-600 text-black font-bold rounded-3xl text-xl">BUY QFC</button>
        </div>

        <div class="card">
            <h3 class="accent mb-4">Sell QFC to Treasury <span id="sell_live_price_display" class="text-sm font-normal opacity-70">( $0.01 )</span></h3>
            <input id="sell_qfc" type="number" step="0.000001" placeholder="Enter QFC Amount to Sell" class="w-full bg-zinc-900 px-6 py-5 rounded-2xl text-xl mb-3" oninput="updateSellPreview()">
            <div id="sell_preview" class="text-emerald-400 text-xl font-bold mb-4">You will receive: $0.00</div>
            <div id="sell_gas" class="text-amber-400 text-sm">1% gas fee → Treasury Vault</div>
            <button onclick="sellQFC()" class="w-full py-6 bg-amber-500 hover:bg-amber-600 text-black font-bold rounded-3xl text-xl">SELL QFC</button>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div class="card">
                <h3 class="accent mb-6">Send QFC</h3>
                <input id="recipient" placeholder="Recipient Address" class="w-full bg-zinc-900 px-6 py-5 rounded-2xl mb-4 font-mono text-sm">
                <input id="send_amount" type="number" step="0.000001" placeholder="Amount QFC" class="w-full bg-zinc-900 px-6 py-5 rounded-2xl mb-6">
                <button onclick="sendQFC()" class="w-full py-6 bg-white text-black font-bold rounded-3xl">SEND QFC</button>
            </div>
            <div class="card">
                <h3 class="accent mb-6">Receive QFC</h3>
                <div id="qr" class="mx-auto bg-white p-4 rounded-2xl w-fit"></div>
                <p id="myaddr" class="font-mono text-sm break-all text-center mt-4"></p>
                <button onclick="scanQR()" class="mt-4 w-full py-4 bg-emerald-500 text-black font-bold rounded-2xl">📷 Scan QR Code</button>
                <button onclick="copyAddress()" class="mt-2 w-full py-4 bg-zinc-700 rounded-2xl font-bold">Copy Address</button>
            </div>
        </div>

        <div class="card">
            <h3 class="accent mb-4">Phantom Jumper Key (Post-Quantum)</h3>
            <div id="morphed_key" class="keybox text-emerald-300">Loading morph...</div>
            <p id="morphed_info" class="text-xs text-center mt-2 opacity-70">Block <span id="block_count">235</span> • Next morph in <span id="morph_timer">2m 0s</span></p>
            <button onclick="refreshKey()" class="mt-6 w-full py-4 bg-zinc-700 rounded-2xl font-bold">Refresh Morph Now</button>
        </div>

        <div class="card flex items-center gap-3">
            <input type="checkbox" id="stay_logged" checked onchange="toggleHeartbeat()">
            <label for="stay_logged" class="text-lg">Stay Logged In (live updates every 3 seconds)</label>
        </div>

        <div class="card">
            <h3 class="accent mb-6">Transaction History (Your Wallet Only)</h3>
            <div id="history" class="max-h-96 overflow-y-auto space-y-3 text-sm"></div>
        </div>
    </div>

    <div id="scanner_modal" class="hidden fixed inset-0 bg-black/90 flex items-center justify-center z-50">
        <div class="card max-w-lg w-full mx-4">
            <div id="reader" style="width:100%;height:300px"></div>
            <button onclick="stopScanner()" class="mt-6 w-full py-4 bg-red-600 text-white rounded-2xl">Cancel Scan</button>
        </div>
    </div>

    <script>
    let myAddress = "";
    let currentSeed = "";
    let currentPin = "";
    let chain_height = 235;
    let html5QrCode;
    let currentLivePrice = 0.01;
    let walletRadarChart;
    let radarData = [];
    let currentRangeHours = 24;

    function initWalletRadar() {
        walletRadarChart = new Chart(document.getElementById('walletRadarChart'), {
            type: 'line',
            data: { labels: [], datasets: [{ label: 'QFC Price (USD)', borderColor: '#00ff88', tension: 0.4, data: [] }] },
            options: { scales: { y: { grid: { color: '#334155' } } } }
        });
    }

    function setRange(hours) {
        currentRangeHours = hours;
        document.querySelectorAll('.range-btn').forEach(btn => btn.classList.remove('active'));
        document.getElementById(`btn-${hours}`).classList.add('active');
        updateRadarChart();
    }

    function updateRadarChart() {
        if (!walletRadarChart) return;
        let filtered = radarData;
        if (currentRangeHours > 0) {
            const cutoff = Date.now() - (currentRangeHours * 60 * 60 * 1000);
            filtered = radarData.filter(point => point.t >= cutoff);
        }
        walletRadarChart.data.labels = filtered.map(p => new Date(p.t).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}));
        walletRadarChart.data.datasets[0].data = filtered.map(p => p.p);
        walletRadarChart.update();
    }

    async function autoRestoreWallet() {
        console.log("[Wallet] autoRestoreWallet started - forcing hero screen first");
        document.getElementById('entry_hero').classList.remove('hidden');
        document.getElementById('wallet_content').classList.add('hidden');

        const savedAddress = localStorage.getItem("qfc_wallet_address");
        const savedSeed = localStorage.getItem("qfc_seed");
        const savedPin = localStorage.getItem("qfc_pin");

        if (savedAddress && savedSeed && savedPin) {
            console.log("[Wallet] Saved wallet found → restoring");
            myAddress = savedAddress;
            currentSeed = savedSeed;
            currentPin = savedPin;

            document.getElementById('entry_hero').classList.add('hidden');
            document.getElementById('wallet_content').classList.remove('hidden');
            document.getElementById('myaddr').innerText = myAddress;
            document.getElementById('qr').innerHTML = `<img src="https://api.qrserver.com/v1/create-qr-code/?size=240x240&data=${myAddress}" class="mx-auto rounded-xl">`;

            await updateUI(true);
            if (document.getElementById('stay_logged').checked) startHeartbeat();

            const urlParams = new URLSearchParams(window.location.search);
            if (urlParams.get('success') === 'true') {
                history.replaceState({}, document.title, '/wallet');
                const toast = document.createElement('div');
                toast.className = 'fixed bottom-6 right-6 bg-emerald-500 text-black px-8 py-4 rounded-3xl shadow-2xl success-toast flex items-center gap-3';
                toast.innerHTML = `✅ Payment successful! CASH balance updated.`;
                document.body.appendChild(toast);
                setTimeout(() => toast.remove(), 4500);
                await updateUI(true);
            }
            return true;
        } else {
            console.log("[Wallet] No saved wallet → showing Create New / Recover hero screen");
            return false;
        }
    }

    async function createNewWallet() {
        const words = ["apple","banana","cherry","delta","echo","foxtrot","golf","hotel","india","juliet","kilo","lima","mike","november","oscar","papa","quebec","romeo","sierra","tango","uniform","victor","whiskey","xray","yankee","zulu"];
        currentSeed = Array.from({length:12}, () => words[Math.floor(Math.random()*words.length)]).join(" ");
        currentPin = String(100000 + Math.floor(Math.random()*900000));
        const res = await fetch(`/derive_address?seed=${encodeURIComponent(currentSeed)}&pin=${currentPin}`);
        const data = await res.json();
        myAddress = data.address;
        document.getElementById('modal_seed').innerText = currentSeed;
        document.getElementById('modal_pin').innerText = currentPin;
        document.getElementById('modal_addr').innerText = myAddress;
        document.getElementById('confirm_written').checked = false;
        document.getElementById('confirm_btn').disabled = true;
        document.getElementById('new_wallet_modal').classList.remove('hidden');
    }

    function checkConfirm() { 
        document.getElementById('confirm_btn').disabled = !document.getElementById('confirm_written').checked; 
    }

    function confirmNewWallet() {
        if (!document.getElementById('confirm_written').checked) return;
        document.getElementById('new_wallet_modal').classList.add('hidden');
        localStorage.setItem("qfc_wallet_address", myAddress);
        localStorage.setItem("qfc_seed", currentSeed);
        localStorage.setItem("qfc_pin", currentPin);
        showWalletContent();
    }

    function showRecover() { document.getElementById('recover_modal').classList.remove('hidden'); }
    function hideRecover() { document.getElementById('recover_modal').classList.add('hidden'); }

    async function recoverWallet() {
        let seed = document.getElementById('recover_seed').value.trim();
        let pin = document.getElementById('recover_pin').value.trim();
        if (!seed || !pin) return alert("Enter seed and PIN");
        const res = await fetch('/recover', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({seed, pin})});
        const data = await res.json();
        if (data.success) {
            hideRecover();
            currentSeed = seed;
            currentPin = pin;
            myAddress = data.address;
            localStorage.setItem("qfc_wallet_address", myAddress);
            localStorage.setItem("qfc_seed", seed);
            localStorage.setItem("qfc_pin", pin);
            showWalletContent();
            alert("✅ Wallet recovered on new device!");
        } else {
            alert("❌ Invalid seed or PIN");
        }
    }

    function showWalletContent() {
        document.getElementById('entry_hero').classList.add('hidden');
        document.getElementById('wallet_content').classList.remove('hidden');
        document.getElementById('myaddr').innerText = myAddress;
        document.getElementById('qr').innerHTML = `<img src="https://api.qrserver.com/v1/create-qr-code/?size=240x240&data=${myAddress}" class="mx-auto rounded-xl">`;
        updateUI(true);
        if (document.getElementById('stay_logged').checked) startHeartbeat();
    }

    async function updateUI(force = false) {
        const res = await fetch('/state');
        const data = await res.json();
        const qfcBal = parseFloat(data.wallet_balances[myAddress] || 0);
        const usdBal = parseFloat(data.wallet_usd_balances[myAddress] || 0);
        const cashValue = (qfcBal * (data.live_price || 0.01)).toFixed(2);

        document.getElementById('balance').innerText = qfcBal.toFixed(6);
        document.getElementById('qfc_value').innerText = `Cash Value: $${cashValue}`;
        document.getElementById('usd_balance').innerText = '$' + usdBal.toFixed(2) + ' CASH';

        chain_height = data.chain_height || 235;
        currentLivePrice = data.live_price || 0.01;

        radarData.push({t: Date.now(), p: currentLivePrice});
        if (radarData.length > 800) radarData.shift();
        updateRadarChart();

        updateBuyPreview();
        updateSellPreview();

        let html = '';
        (data.history || []).slice().reverse().forEach(tx => {
            if (typeof tx !== 'object') return;
            let line = '';
            let addrShort = '';
            let copyAddr = '';
            if (tx.type === 'deposit' && tx.to === myAddress) line = `[${tx.time}] ✅ Deposited $${tx.usd} CASH`;
            else if (tx.type === 'buy' && tx.to === myAddress) line = `[${tx.time}] Bought ${tx.qfc} QFC for $${tx.usd}`;
            else if (tx.type === 'sell' && tx.from === myAddress) line = `[${tx.time}] Sold ${tx.qfc} QFC for $${tx.usd}`;
            else if (tx.type === 'sent' && tx.from === myAddress) {
                addrShort = tx.to ? tx.to.substring(0,12) + '...' : '';
                copyAddr = tx.to || '';
                line = `[${tx.time}] Sent ${tx.amount} QFC to <span class="copy-addr" data-addr="${copyAddr}">${addrShort}</span>`;
            } else if ((tx.type === 'received' || tx.type === 'treasury_sent') && tx.to === myAddress) {
                addrShort = (tx.from && tx.from.length > 10) ? tx.from.substring(0,12) + '...' : 'QFC Treasury';
                copyAddr = (tx.from && tx.from.length > 10) ? tx.from : '';
                line = `[${tx.time}] Received ${tx.amount} QFC from <span class="copy-addr" data-addr="${copyAddr}">${addrShort}</span>`;
            } else if (tx.type === 'mined' && tx.to === myAddress) line = `[${tx.time}] Mined +${tx.amount} QFC`;
            else if (tx.type === 'monthly_yield' && tx.to === myAddress) line = `[${tx.time}] Monthly Basic Income +${tx.amount} QFC (~$${tx.usd_value || 'N/A'})`;
            else if (tx.type === 'pool_bonus' && tx.to === myAddress) line = `[${tx.time}] Holder Pool Bonus +${tx.amount} QFC`;
            else if (tx.type === 'withdrawal' && tx.from === myAddress) line = `[${tx.time}] Withdrawn $${tx.usd} to bank account`;
            if (line) html += `<div class="tx-item">${line}</div>`;
        });
        document.getElementById('history').innerHTML = html || '<p class="opacity-50">No transactions yet</p>';

        document.querySelectorAll('.copy-addr').forEach(el => {
            el.addEventListener('click', (e) => {
                e.stopPropagation();
                const addr = el.getAttribute('data-addr');
                if (addr) navigator.clipboard.writeText(addr);
            });
        });

        if (force) refreshKey();
    }

    function updateBuyPreview() {
        const usd = parseFloat(document.getElementById('buy_usd').value || 0);
        if (usd > 0 && currentLivePrice > 0) {
            const qfc = (usd / currentLivePrice).toFixed(6);
            const gas = (usd * 0.01).toFixed(2);
            document.getElementById('buy_preview').innerText = `You will receive: ${qfc} QFC`;
            document.getElementById('buy_gas').innerText = `1% gas fee: $${gas} → Treasury Vault`;
        } else {
            document.getElementById('buy_preview').innerText = `You will receive: 0.000000 QFC`;
        }
    }

    function updateSellPreview() {
        const qfc = parseFloat(document.getElementById('sell_qfc').value || 0);
        if (qfc > 0 && currentLivePrice > 0) {
            const usd = (qfc * currentLivePrice).toFixed(2);
            const gas = (parseFloat(usd) * 0.01).toFixed(2);
            document.getElementById('sell_preview').innerText = `You will receive: $${usd}`;
            document.getElementById('sell_gas').innerText = `1% gas fee: $${gas} → Treasury Vault`;
        } else {
            document.getElementById('sell_preview').innerText = `You will receive: $0.00`;
        }
    }

    async function buyQFC() {
        const usd = parseFloat(document.getElementById('buy_usd').value || 0);
        if (usd <= 0) return alert("Enter valid USD amount");
        const form = new FormData();
        form.append('usd', usd);
        form.append('buyer_address', myAddress);
        try {
            const buyRes = await fetch('/buy_qfc', {method: 'POST', body: form});
            if (!buyRes.ok) throw new Error(`HTTP ${buyRes.status}`);
            const buyData = await buyRes.json();
            alert(buyData.message || "✅ Transaction completed");
            updateUI(true);
        } catch (err) {
            console.error(err);
            alert("❌ Buy failed: " + err.message);
        }
    }

    async function sellQFC() {
        const qfc = parseFloat(document.getElementById('sell_qfc').value || 0);
        if (qfc <= 0) return alert("Enter valid QFC amount");
        const form = new FormData();
        form.append('qfc', qfc);
        form.append('seller_address', myAddress);
        try {
            const res = await fetch('/sell_qfc', {method: 'POST', body: form});
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            alert(data.message || "✅ Transaction completed");
            updateUI(true);
        } catch (err) {
            console.error(err);
            alert("❌ Sell failed: " + err.message);
        }
    }

    async function sendQFC() {
        const recipient = document.getElementById('recipient').value.trim();
        const amount = parseFloat(document.getElementById('send_amount').value || 0);
        if (!recipient || amount <= 0) return alert("Invalid");
        if (recipient === myAddress) return alert("Cannot send to yourself");
        const form = new FormData();
        form.append('sender', myAddress);
        form.append('recipient', recipient);
        form.append('amount', amount);
        await fetch('/send', {method:'POST', body: form});
        updateUI(true);
    }

    function scanQR() {
        const modal = document.getElementById('scanner_modal');
        modal.classList.remove('hidden');
        html5QrCode = new Html5Qrcode("reader");
        html5QrCode.start({facingMode: "environment"}, {fps: 10, qrbox: 250}, (decodedText) => {
            document.getElementById('recipient').value = decodedText;
            stopScanner();
        });
    }

    function stopScanner() {
        if (html5QrCode) html5QrCode.stop();
        document.getElementById('scanner_modal').classList.add('hidden');
    }

    function copyAddress() {
        navigator.clipboard.writeText(myAddress);
        alert("Address copied!");
    }

    async function refreshKey() {
        const res = await fetch(`/morphed_key?seed=${encodeURIComponent(currentSeed)}&pin=${encodeURIComponent(currentPin)}&height=${chain_height}`);
        const key = await res.text();
        document.getElementById('morphed_key').innerText = key;
        document.getElementById('block_count').innerText = chain_height;
    }

    async function manualRefresh() { updateUI(true); }

    function toggleHeartbeat() {
        if (document.getElementById('stay_logged').checked) startHeartbeat();
        else if (window.heartbeatInterval) clearInterval(window.heartbeatInterval);
    }

    function startHeartbeat() {
        if (window.heartbeatInterval) clearInterval(window.heartbeatInterval);
        window.heartbeatInterval = setInterval(() => updateUI(), 3000);
    }

    async function exportWallet() {
        const res = await fetch('/export_wallet');
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = 'my_qfc_wallet.json'; a.click();
        URL.revokeObjectURL(url);
    }

    async function addFunds() {
        const amount = prompt("How much USD would you like to deposit?", "100");
        if (!amount || isNaN(parseFloat(amount))) return;
        const usd = parseFloat(amount);
        const form = new FormData();
        form.append('usd_amount', usd);
        form.append('buyer_address', myAddress);
        try {
            const res = await fetch('/create-checkout-session', {method: 'POST', body: form});
            const data = await res.json();
            if (data.url) window.location.href = data.url;
        } catch (err) {
            alert("❌ Could not start payment: " + err.message);
        }
    }

    async function withdrawFunds() {
        const currentUsd = parseFloat(document.getElementById('usd_balance').innerText.replace('$', '').replace(' CASH', '')) || 0;
        if (currentUsd <= 0) return alert("No CASH available to withdraw.");
        const amount = prompt(`How much CASH would you like to withdraw? (Available: $${currentUsd.toFixed(2)})`, currentUsd.toFixed(2));
        if (!amount || isNaN(parseFloat(amount))) return;
        const usd = parseFloat(amount);
        if (usd > currentUsd) return alert("Insufficient CASH.");
        const form = new FormData();
        form.append('usd', usd);
        form.append('wallet_address', myAddress);
        try {
            const res = await fetch('/withdraw', {method: 'POST', body: form});
            const data = await res.json();
            alert(data.message);
            updateUI(true);
        } catch (err) {
            alert("❌ Withdrawal failed: " + err.message);
        }
    }

    window.onload = () => {
        initWalletRadar();
        autoRestoreWallet();
    };
    </script>
</body>
</html>
    """
    return HTMLResponse(html)

# ====================== TREASURY HTML (updated to show adaptive reserve) ======================
TREASURY_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>QuantumForge Treasury Operator Console</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { background: #0a0a1f; color: #e0ffe0; }
        .card { background: #111827; border: 2px solid #00ff88; border-radius: 24px; padding: 40px 32px; margin-bottom: 24px; text-align: center; }
        .number { font-size: 36px; font-weight: 700; white-space: nowrap; line-height: 1.1; }
        .accent { color: #00ff88; }
        .keybox { font-family: monospace; background: #1a1a2e; padding: 16px; border-radius: 12px; word-break: break-all; font-size: 13px; }
        .range-btn { padding: 6px 12px; margin: 0 4px; border-radius: 9999px; background: #1a2338; color: #e0ffe0; cursor: pointer; }
        .range-btn.active { background: #00ff88; color: #111827; font-weight: bold; }
        input { background: #1a1a2e; color: #e0ffe0; border: 2px solid #00ff88; padding: 12px; border-radius: 12px; width: 100%; margin: 10px 0; font-size: 18px; }
    </style>
</head>
<body class="p-8 max-w-6xl mx-auto">
    <h1 class="text-5xl font-bold accent text-center mb-12">QuantumForge Treasury Operator Console</h1>
    
    <div class="grid grid-cols-3 gap-8">
        <div class="card"><p class="opacity-70">Treasury QFC</p><div id="treasury_qfc" class="number accent">10500000.000000</div></div>
        <div class="card"><p class="opacity-70">USD Vault</p><div id="usd_vault" class="number accent">$50000.00</div></div>
        <div class="card"><p class="opacity-70">Chain Height</p><div id="chain" class="number accent">235</div></div>
    </div>

    <div class="card">
        <button onclick="addFundsToTreasury()" class="w-full py-8 bg-emerald-500 hover:bg-emerald-600 text-black font-bold rounded-3xl text-2xl">💵 Add Funds to Treasury (Stripe)</button>
    </div>

    <div class="card">
        <h3 class="accent mb-4">Live QFC Price (USD)</h3>
        <div id="live_price_display" class="text-6xl font-bold accent">$0.01</div>
        <canvas id="radarChart" height="180"></canvas>
        <div class="flex justify-center mt-4">
            <span onclick="setRange(1)" class="range-btn" id="btn-1">1h</span>
            <span onclick="setRange(24)" class="range-btn active" id="btn-24">24h</span>
            <span onclick="setRange(168)" class="range-btn" id="btn-168">7d</span>
            <span onclick="setRange(720)" class="range-btn" id="btn-720">30d</span>
            <span onclick="setRange(0)" class="range-btn" id="btn-0">All</span>
        </div>
    </div>

    <div class="card">
        <h3 class="accent mb-4">Phantom Jumper Key (Post-Quantum)</h3>
        <div id="treasury_morphed_key" class="keybox text-emerald-300">Loading morph...</div>
        <p id="treasury_morphed_info" class="text-xs text-center mt-2 opacity-70">Block <span id="treasury_block">235</span> • Next morph in <span id="morph_timer">2m 0s</span></p>
        <button onclick="refreshTreasuryMorph()" class="mt-6 w-full py-4 bg-zinc-700 rounded-2xl font-bold">Refresh Morph Now</button>
    </div>

    <div class="card">
        <h3 class="accent mb-4">Next Monthly Distribution (30 days)</h3>
        <p id="next_yield" class="text-2xl">Calculating...</p>
    </div>

    <div class="card">
        <h3 class="accent mb-4">Auto Mining</h3>
        <p>Next auto-mine in <span id="auto_mine_timer" class="accent text-4xl font-mono">30m 0s</span></p>
    </div>

    <div class="card">
        <h3 class="accent mb-4">Holder Reward Pool</h3>
        <div id="holder_pool" class="text-4xl font-bold accent">0.000000 QFC</div>
        <p class="text-sm opacity-70">Next bonus when pool ≥ 10 QFC</p>
    </div>

    <div class="card">
        <h3 class="accent mb-4">Supply Dynamics</h3>
        <p>Current Mining Reward: <span id="current_reward" class="accent">25.0</span> QFC</p>
        <p>Next Halving at Block: <span id="next_halving" class="accent">735</span></p>
    </div>

    <div class="card">
        <h3 class="accent text-2xl mb-4">Adaptive Liquidity Reserve (Intelligent Protection)</h3>
        <div id="adaptive_reserve" class="text-4xl font-bold accent">$250.00</div>
        <p class="text-sm opacity-70">Minimum protected USD balance (scales automatically with treasury health)</p>
    </div>

    <div class="grid grid-cols-2 gap-6">
        <button onclick="mineBlock()" class="card py-10 text-2xl font-bold bg-emerald-500 hover:bg-emerald-600 text-black rounded-3xl">Mine Block (+25 QFC)<br><small>70% Treasury • 30% Holder Pool</small></button>
        <button onclick="distributeYield()" class="card py-10 text-2xl font-bold bg-amber-500 hover:bg-amber-600 text-black rounded-3xl">Force Monthly Distribution</button>
        <button onclick="airdrop()" class="card py-10 text-2xl font-bold bg-violet-600 hover:bg-violet-700 text-white rounded-3xl">Airdrop 10 Wallets × 5000 QFC</button>
        <button onclick="sendFromTreasury()" class="card py-10 text-2xl font-bold bg-white hover:bg-gray-100 text-black rounded-3xl">Send from Treasury</button>
    </div>

    <div class="card">
        <h3 class="accent text-2xl mb-6">Safe Profit Withdrawal (Liquidity Protected)</h3>
        <div id="available_profit" class="text-3xl accent">$0.00</div>
        <input id="withdraw_amount" type="number" step="0.01" placeholder="Amount to Withdraw (USD)" class="w-full px-6 py-4 rounded-2xl text-xl mb-4">
        <input id="withdraw_pin" type="password" maxlength="14" placeholder="Enter Treasury PIN" class="w-full px-6 py-4 rounded-2xl text-xl mb-4">
        <button onclick="withdrawProfit()" class="w-full py-6 bg-red-600 hover:bg-red-700 text-white font-bold rounded-3xl">SAFE WITHDRAW PROFIT → BANK</button>
        <p class="text-xs opacity-70 mt-4">Only profit above the adaptive minimum reserve can be withdrawn.</p>
    </div>

    <div class="card">
        <h3 class="accent text-2xl mb-6">Transaction History</h3>
        <div id="history" class="max-h-96 overflow-y-auto space-y-3 text-sm"></div>
    </div>

    <script>
    let radarChart;
    let radarData = [];
    let currentRangeHours = 24;

    function initRadar() {
        radarChart = new Chart(document.getElementById('radarChart'), {
            type: 'line',
            data: { labels: [], datasets: [{ label: 'QFC Price (USD)', borderColor: '#00ff88', tension: 0.4, data: [] }] },
            options: { scales: { y: { grid: { color: '#334155' } } } }
        });
    }

    function setRange(hours) {
        currentRangeHours = hours;
        document.querySelectorAll('.range-btn').forEach(btn => btn.classList.remove('active'));
        document.getElementById(`btn-${hours}`).classList.add('active');
        updateRadarChart();
    }

    function updateRadarChart() {
        if (!radarChart) return;
        let filtered = radarData;
        if (currentRangeHours > 0) {
            const cutoff = Date.now() - (currentRangeHours * 60 * 60 * 1000);
            filtered = radarData.filter(point => point.t >= cutoff);
        }
        radarChart.data.labels = filtered.map(p => new Date(p.t).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}));
        radarChart.data.datasets[0].data = filtered.map(p => p.p);
        radarChart.update();
    }

    async function updateUI() {
        const data = await (await fetch('/state')).json();
        document.getElementById('treasury_qfc').innerText = parseFloat(data.treasury_balance).toFixed(6);
        document.getElementById('usd_vault').innerText = '$' + parseFloat(data.treasury_usd || 0).toFixed(2);
        document.getElementById('chain').innerText = data.chain_height;
        document.getElementById('treasury_block').innerText = data.chain_height;
        document.getElementById('live_price_display').innerText = '$' + parseFloat(data.live_price || 0.01).toFixed(4);
        document.getElementById('holder_pool').innerText = parseFloat(data.holder_reward_pool || 0).toFixed(6) + " QFC";
        document.getElementById('current_reward').innerText = data.current_block_reward.toFixed(1);
        document.getElementById('next_halving').innerText = (data.chain_height + (500 - data.chain_height % 500)).toString();

        const now = Date.now() / 1000;
        const lastYield = data.last_yield_time || now - 2592000;
        const secondsLeft = Math.max(0, 2592000 - (now - lastYield));
        const days = Math.floor(secondsLeft / 86400);
        const hours = Math.floor((secondsLeft % 86400) / 3600);
        const minutes = Math.floor((secondsLeft % 3600) / 60);
        document.getElementById('next_yield').innerText = `Next yield in ${days}d ${hours}h ${minutes}m`;

        const lastMine = data.last_auto_mine_time || now - 1800;
        const interval = data.mining_interval || 1800;
        let mineSecondsLeft = Math.max(0, interval - (now - lastMine));
        if (mineSecondsLeft <= 0) {
            await fetch('/mine', {method: 'POST'});
            mineSecondsLeft = interval;
        }
        const mineM = Math.floor(mineSecondsLeft / 60);
        const mineS = Math.floor(mineSecondsLeft % 60);
        document.getElementById('auto_mine_timer').innerText = `${mineM}m ${mineS}s`;

        radarData.push({t: Date.now(), p: parseFloat(data.live_price || 0.01)});
        if (radarData.length > 800) radarData.shift();
        updateRadarChart();

        let html = '';
        (data.history || []).slice().reverse().forEach(tx => {
            let line = typeof tx === 'object' ? `[${tx.time}] ${tx.type === 'monthly_yield' ? 'Monthly Basic Income' : tx.type} ${tx.amount || tx.qfc || ''} QFC` : tx;
            html += `<div class="bg-zinc-900 p-5 rounded-2xl">${line}</div>`;
        });
        document.getElementById('history').innerHTML = html || '<p class="opacity-50">No transactions yet</p>';

        const available = Math.max(0, parseFloat(data.treasury_usd || 0) - parseFloat(data.adaptive_reserve || 250));
        document.getElementById('available_profit').innerText = '$' + available.toFixed(2);
        document.getElementById('adaptive_reserve').innerText = '$' + parseFloat(data.adaptive_reserve || 250).toFixed(2);
    }

    async function mineBlock() { await fetch('/mine',{method:'POST'}); updateUI(); }

    async function distributeYield() {
        const pin = prompt("Enter Treasury PIN to force monthly distribution:");
        if (pin !== "79369943077973") {
            alert("❌ Incorrect Treasury PIN");
            return;
        }
        const res = await fetch('/yield', {method: 'POST'});
        const data = await res.json();
        alert(data.message);
        updateUI();
    }

    async function airdrop() { await fetch('/airdrop',{method:'POST'}); updateUI(); }

    async function sendFromTreasury() {
        const recipient = prompt("Recipient Address:", "d0ff5d049bcc4ecf176b7523901a1f4c0a429d98285966ca1919ceb0291b2638");
        const amount = parseFloat(prompt("Amount QFC to send:", "100"));
        const pin = prompt("Enter Treasury PIN to confirm:");
        if (pin !== "79369943077973") return alert("❌ Incorrect Treasury PIN");
        if (!amount || !recipient) return alert("Invalid input");
        const form = new FormData();
        form.append('recipient', recipient);
        form.append('amount', amount);
        await fetch('/send_from_treasury', {method:'POST', body: form});
        updateUI();
    }

    async function refreshTreasuryMorph() {
        const res = await fetch('/morphed_key?seed=apple banana cherry delta echo foxtrot golf hotel india juliet kilo lima mike november oscar papa quebec romeo sierra tango uniform victor whiskey xray yankee zulu&pin=424242&height=' + document.getElementById('chain').innerText);
        const key = await res.text();
        document.getElementById('treasury_morphed_key').innerText = key;
    }

    async function withdrawProfit() {
        const amount = parseFloat(document.getElementById('withdraw_amount').value || 0);
        const pin = document.getElementById('withdraw_pin').value.trim();
        if (!amount || amount <= 0) return alert("Enter a valid amount");
        if (pin !== "79369943077973") return alert("❌ Incorrect Treasury PIN");
        if (confirm(`Withdraw $${amount.toFixed(2)} safely to bank?`)) {
            const form = new FormData();
            form.append('amount', amount);
            const res = await fetch('/withdraw_profit', {method: 'POST', body: form});
            const data = await res.json();
            alert(data.message);
            updateUI();
        }
    }

    async function addFundsToTreasury() {
        const amount = prompt("How much USD would you like to add to the Treasury?", "1000");
        if (!amount || isNaN(parseFloat(amount))) return;
        const form = new FormData();
        form.append('usd_amount', parseFloat(amount));
        form.append('buyer_address', 'treasury');
        try {
            const res = await fetch('/create-checkout-session', {method: 'POST', body: form});
            const data = await res.json();
            if (data.url) window.location.href = data.url;
        } catch (err) {
            alert("❌ Could not start payment: " + err.message);
        }
    }

    window.onload = () => { 
        initRadar(); 
        updateUI(); 
        setInterval(updateUI, 3000); 
    };
    </script>
</body>
</html>
"""

@app.get(TREASURY_PATH, response_class=HTMLResponse)
async def treasury_console(pw: str = None):
    if pw != TREASURY_PASSWORD:
        return HTMLResponse("Access Denied", 403)
    return HTMLResponse(TREASURY_HTML)

# ====================== STRIPE CHECKOUT ======================
@app.post("/create-checkout-session")
async def create_checkout_session(usd_amount: float = Form(...), buyer_address: str = Form(None)):
    if usd_amount <= 0:
        raise HTTPException(400, "Invalid amount")
    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": "QuantumForge Coin (QFC) - Add Funds"},
                    "unit_amount": int(usd_amount * 100),
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url="http://127.0.0.1:8000/wallet?success=true",
            cancel_url="http://127.0.0.1:8000/wallet?cancelled=true",
            metadata={"buyer_address": buyer_address or "treasury", "usd_amount": str(usd_amount)},
        )
        return {"url": checkout_session.url}
    except Exception as e:
        raise HTTPException(400, str(e))

# ====================== STRIPE WEBHOOK ======================
@app.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    print(f"[WEBHOOK] Received event at {datetime.now()} | Signature present: {bool(sig_header)} | Payload length: {len(payload)}")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
        print(f"[WEBHOOK] ✅ Signature verified - Event type: {event['type']}")
    except Exception as e:
        print(f"[WEBHOOK] ❌ Signature verification failed: {e}")
        raise HTTPException(400, "Invalid signature")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        buyer_address = session["metadata"]["buyer_address"]
        usd_amount = float(session["metadata"]["usd_amount"])
        print(f"[WEBHOOK] Payment successful - USD: ${usd_amount} | Buyer: {buyer_address}")

        if buyer_address == "treasury":
            global treasury_usd
            treasury_usd += usd_amount
            transactions.append({"type": "treasury_deposit", "usd": usd_amount, "time": datetime.now().strftime("%Y-%m-%d %H:%M")})
            print(f"[WEBHOOK] Treasury USD increased by ${usd_amount}")
        else:
            wallet_usd_balances[buyer_address] = wallet_usd_balances.get(buyer_address, 0) + usd_amount
            transactions.append({"type": "deposit", "usd": usd_amount, "to": buyer_address, "time": datetime.now().strftime("%Y-%m-%d %H:%M")})
            print(f"[WEBHOOK] Wallet CASH balance for {buyer_address} increased by ${usd_amount}")

        save_state()

    return JSONResponse({"status": "success"})

# ====================== WITHDRAW ENDPOINTS (now uses adaptive reserve) ======================
@app.post("/withdraw")
async def withdraw(usd: float = Form(...), wallet_address: str = Form(...)):
    if wallet_usd_balances.get(wallet_address, 0) < usd:
        return {"message": "Insufficient CASH"}
    wallet_usd_balances[wallet_address] -= usd
    transactions.append({"type": "withdrawal", "usd": usd, "from": wallet_address, "time": time.strftime("%Y-%m-%d %H:%M")})
    save_state()
    
    try:
        payout = stripe.Payout.create(amount=int(usd * 100), currency="usd")
        print(f"✅ Stripe payout created for wallet {wallet_address}: {payout.id}")
        return {"message": f"✅ $${usd:.2f} withdrawn to bank account"}
    except Exception as e:
        error_str = str(e).lower()
        if "insufficient funds" in error_str or "card balance is too low" in error_str:
            print(f"✅ Test-mode payout skipped (normal in Stripe test mode) — internal withdrawal succeeded")
            return {"message": f"✅ $${usd:.2f} withdrawn (test mode — no real payout sent)"}
        else:
            print(f"Payout error (still logged internally): {e}")
            return {"message": f"✅ $${usd:.2f} withdrawn internally — payout failed ({e})"}

@app.post("/withdraw_profit")
async def withdraw_profit(amount: float = Form(...)):
    global treasury_usd
    min_reserve = get_adaptive_min_reserve()
    if treasury_usd - amount < min_reserve:
        return {"message": f"Cannot withdraw — would go below adaptive minimum reserve of ${min_reserve:.2f}"}
    treasury_usd -= amount
    transactions.append({"type": "treasury_withdrawal", "usd": amount, "time": time.strftime("%Y-%m-%d %H:%M")})
    save_state()
    
    try:
        payout = stripe.Payout.create(amount=int(amount * 100), currency="usd")
        print(f"✅ Stripe payout created from treasury: {payout.id}")
        return {"message": f"✅ $${amount:.2f} safely withdrawn from treasury"}
    except Exception as e:
        error_str = str(e).lower()
        if "insufficient funds" in error_str or "card balance is too low" in error_str:
            print(f"✅ Test-mode payout skipped (normal in Stripe test mode) — internal withdrawal succeeded")
            return {"message": f"✅ $${amount:.2f} withdrawn (test mode — no real payout sent)"}
        else:
            print(f"Payout error (still logged internally): {e}")
            return {"message": f"✅ $${amount:.2f} withdrawn internally — payout failed ({e})"}

# ====================== RECOVER ======================
@app.post("/recover")
async def recover(data: dict):
    seed = data.get("seed")
    pin = data.get("pin")
    if not seed or not pin:
        return {"success": False}
    address = derive_address(seed, pin)
    if address in wallet_balances or address == my_addr:
        return {"success": True, "address": address}
    else:
        return {"success": False}

# ====================== BUY / SELL / SEND / MINE / YIELD / AIRDROP ======================
@app.post("/buy_qfc")
async def buy_qfc(usd: float = Form(...), buyer_address: str = Form(None)):
    load_state()
    global treasury_balance, treasury_usd, recent_buy_volume
    if usd <= 0: return {"message": "Invalid amount"}
    live_price = min(0.50, 0.01 * (1 + (1 - treasury_balance / TOTAL_SUPPLY_CAP) * 1.5))
    qfc_amount = round(usd / live_price, 6)
    gas = round(usd * GAS_FEE_PERCENT, 2)
    buyer = buyer_address or my_addr
    current_usd = wallet_usd_balances.get(buyer, 0.0)
    if usd > current_usd: return {"message": "Insufficient CASH. Please add funds."}
    treasury_balance -= qfc_amount
    treasury_usd += usd + gas
    wallet_balances[buyer] = wallet_balances.get(buyer, 0.0) + qfc_amount
    wallet_usd_balances[buyer] = current_usd - usd
    recent_buy_volume += usd
    transactions.append({"type": "buy", "usd": usd, "qfc": qfc_amount, "gas": gas, "to": buyer, "time": time.strftime("%Y-%m-%d %H:%M")})
    save_state()
    return {"message": f"✅ Bought {qfc_amount} QFC for ${usd} (1% gas ${gas} to Treasury)"}

@app.post("/sell_qfc")
async def sell_qfc(qfc: float = Form(...), seller_address: str = Form(None)):
    load_state()
    global treasury_balance, treasury_usd
    if qfc <= 0: return {"message": "Invalid amount"}
    live_price = min(0.50, 0.01 * (1 + (1 - treasury_balance / TOTAL_SUPPLY_CAP) * 1.5))
    usd_amount = round(qfc * live_price, 2)
    gas = round(usd_amount * GAS_FEE_PERCENT, 2)
    seller = seller_address or my_addr
    if wallet_balances.get(seller, 0) < qfc: return {"message": "Insufficient QFC"}
    if treasury_usd < usd_amount: return {"message": "Treasury has insufficient USD liquidity for this sale"}
    wallet_balances[seller] -= qfc
    wallet_usd_balances[seller] = (wallet_usd_balances.get(seller, 0.0) + usd_amount - gas)
    treasury_balance += qfc
    treasury_usd -= usd_amount
    treasury_usd += gas
    transactions.append({"type": "sell", "qfc": qfc, "usd": usd_amount, "gas": gas, "from": seller, "time": time.strftime("%Y-%m-%d %H:%M")})
    save_state()
    return {"message": f"✅ Sold {qfc} QFC for ${usd_amount} (1% gas ${gas} to Treasury)"}

@app.post("/send_from_treasury")
async def api_send_from_treasury(recipient: str = Form(...), amount: float = Form(...)):
    global treasury_balance
    if treasury_balance < amount:
        return {"message": "Insufficient funds"}
    treasury_balance -= amount
    wallet_balances[recipient] = wallet_balances.get(recipient, 0.0) + amount
    transactions.append({"type": "treasury_sent", "amount": amount, "to": recipient, "from": "QFC Treasury", "time": time.strftime("%Y-%m-%d %H:%M")})
    transactions.append({"type": "received", "amount": amount, "from": "QFC Treasury", "to": recipient, "time": time.strftime("%Y-%m-%d %H:%M")})
    save_state()
    return {"message": f"✅ Sent {amount} QFC to wallet"}

@app.get("/state")
async def get_state():
    load_state()
    live_price = min(0.50, 0.01 * (1 + (1 - treasury_balance / TOTAL_SUPPLY_CAP) * 1.5))
    radar_history.append({"t": int(time.time() * 1000), "p": round(live_price, 4)})
    if len(radar_history) > 1000:
        radar_history.pop(0)
    save_state()
    return {
        "treasury_balance": treasury_balance,
        "treasury_usd": treasury_usd,
        "chain_height": chain_height,
        "history": transactions[-40:],
        "wallet_balances": wallet_balances,
        "wallet_usd_balances": wallet_usd_balances,
        "live_price": round(live_price, 4),
        "last_yield_time": LAST_YIELD_TIME,
        "last_auto_mine_time": LAST_AUTO_MINE_TIME,
        "mining_interval": calculate_mining_interval(),
        "holder_reward_pool": holder_reward_pool,
        "current_block_reward": current_block_reward,
        "adaptive_reserve": get_adaptive_min_reserve()
    }

@app.post("/mine")
async def api_mine():
    await perform_mine()
    return {"message": f"Block mined — manual trigger successful"}

@app.post("/yield")
async def api_yield():
    global treasury_balance, LAST_YIELD_TIME
    if treasury_balance < 1000:
        return {"message": "Treasury too low"}
    live_price = min(0.50, 0.01 * (1 + (1 - treasury_balance / TOTAL_SUPPLY_CAP) * 1.5))
    eligible = {addr: bal for addr, bal in wallet_balances.items() if bal >= MIN_YIELD_BALANCE}
    if not eligible:
        return {"message": "No eligible wallets"}
    total_eligible = sum(eligible.values())
    dynamic_rate = MIN_YIELD_RATE + (MAX_YIELD_RATE - MIN_YIELD_RATE) * (1 - treasury_balance / TOTAL_SUPPLY_CAP)
    monthly_pool = treasury_balance * min(dynamic_rate, TREASURY_MAX_MONTHLY_PCT)
    for addr, bal in eligible.items():
        reward = (bal / total_eligible) * monthly_pool
        wallet_balances[addr] = wallet_balances.get(addr, 0) + reward
        usd_equiv = round(reward * live_price, 2)
        transactions.append({"type": "monthly_yield", "amount": round(reward, 6), "usd_value": usd_equiv, "time": time.strftime("%Y-%m-%d %H:%M"), "to": addr})
    treasury_balance -= monthly_pool
    LAST_YIELD_TIME = time.time()
    save_state()
    return {"message": f"✅ Monthly Basic Income distributed to {len(eligible)} wallets (proportional to holdings)"}

@app.post("/airdrop")
async def api_airdrop():
    global treasury_balance
    if treasury_balance < 50000: return {"message": "Treasury too low"}
    treasury_balance -= 50000
    for i in range(10):
        test_addr = f"test_wallet_{i}_{random.randint(1000,9999)}"
        wallet_balances[test_addr] = wallet_balances.get(test_addr, 0) + 5000
        transactions.append({"type": "airdrop", "amount": 5000, "to": test_addr, "time": time.strftime("%Y-%m-%d %H:%M")})
    save_state()
    return {"message": "Airdrop complete — 10 wallets received 5000 QFC each"}

@app.post("/send")
async def api_send(sender: str = Form(...), recipient: str = Form(...), amount: float = Form(...)):
    load_state()
    if wallet_balances.get(sender, 0) < amount:
        return {"message": "Insufficient funds"}
    if sender == recipient:
        return {"message": "Cannot send to self"}
    wallet_balances[sender] -= amount
    wallet_balances[recipient] = wallet_balances.get(recipient, 0.0) + amount
    transactions.append({"type": "sent", "amount": amount, "from": sender, "to": recipient, "time": time.strftime("%Y-%m-%d %H:%M")})
    transactions.append({"type": "received", "amount": amount, "from": sender, "to": recipient, "time": time.strftime("%Y-%m-%d %H:%M")})
    save_state()
    return {"message": "Sent successfully"}

@app.get("/morphed_key")
async def morphed_key(seed: str, pin: str, height: int):
    return get_morphed_key(seed, pin, height)

@app.get("/derive_address")
async def derive_address_endpoint(seed: str, pin: str):
    return {"address": derive_address(seed, pin)}

@app.get("/export_wallet")
async def export_wallet():
    data = {"seed": "apple banana cherry delta echo foxtrot golf hotel india juliet kilo lima mike november oscar papa quebec romeo sierra tango uniform victor whiskey xray yankee zulu", "pin": "424242", "address": my_addr, "qfc_balance": wallet_balances.get(my_addr, 0), "usd_balance": wallet_usd_balances.get(my_addr, 0), "timestamp": time.time()}
    temp_file = "temp_wallet_export.json"
    with open(temp_file, "w") as f:
        json.dump(data, f, indent=2)
    return FileResponse(temp_file, filename="my_qfc_wallet.json", media_type="application/json")

if __name__ == "__main__":
    print("\n🌐 QuantumForge Coin — LIVE ON RAILWAY")
    print("Main landing: http://127.0.0.1:8000")
    print("Wallet: http://127.0.0.1:8000/wallet")
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)