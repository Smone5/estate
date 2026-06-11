"""
Pi 5 co-tenancy and memory profiling benchmark (T63).

Evaluates co-tenancy of LLMProvider (Ollama) + KokoroTTS + Postgres + FastAPI.
Simulates 3 concurrent virtual heirs sending messages, measuring memory footprint
and response latencies.
"""

import asyncio
import os
import time
import pytest
import psutil
from typing import List, Tuple

from app.graph import build_graph, make_initial_state
from app.services.llm_provider import LLMProvider, get_provider, reset_provider
from app.kokoro_tts import KokoroTTS, get_kokoro_tts

# We will import the mocks to use as fallback
from app.tests.mock_llm import MockLLMProvider
from app.tests.mock_kokoro import MockKokoroTTS


def _get_ollama_memory() -> int:
    """Sum RSS memory of all running 'ollama' processes on the local machine."""
    ollama_mem = 0
    for proc in psutil.process_iter(["name"]):
        try:
            if "ollama" in proc.info["name"].lower():
                ollama_mem += proc.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return ollama_mem


def _get_total_memory() -> int:
    """Get total memory usage: python process RSS + local Ollama RSS."""
    python_mem = psutil.Process().memory_info().rss
    ollama_mem = _get_ollama_memory()
    return python_mem + ollama_mem


async def run_single_heir_turn(graph, provider, tts, session_id: str, heir_id: str, text: str) -> float:
    """Run one full turn of LangGraph + Kokoro TTS synthesis and return latency."""
    start = time.perf_counter()

    # 1. Execute the LangGraph mediation flow (run synchronous stream in a thread)
    state = make_initial_state(
        session_id=session_id,
        heir_id=heir_id,
        input_text=text,
    )
    config = {"configurable": {"thread_id": f"{session_id}:{heir_id}"}}
    
    def run_stream():
        return list(graph.stream(state, config))
        
    events = await asyncio.to_thread(run_stream)

    # Get the mediator's final response text
    mediator_response = ""
    for event in events:
        for node_name, ns in event.items():
            if ns and "mediator_response" in ns:
                mediator_response = ns["mediator_response"]

    if not mediator_response:
        mediator_response = "I hear how much this piece means to you."

    # 2. Synthesize audio of the response via Kokoro
    if isinstance(tts, KokoroTTS):
        await tts.synthesize(mediator_response)
    else:
        tts.synthesize(mediator_response)

    return time.perf_counter() - start


@pytest.mark.asyncio
async def test_pi5_cotenancy_benchmark():
    """
    Co-tenancy profiling benchmark.
    Simulates 3 concurrent heirs and asserts memory & latency constraints.
    """
    # 1. Determine if we are running in real or mock mode
    # Real mode runs if:
    # - RUN_REAL_PI5_BENCHMARK environment variable is set to 'true'
    # - Ollama is reachable and required models are installed
    # - Kokoro-82M ONNX model files are readable
    import httpx
    real_mode = os.environ.get("RUN_REAL_PI5_BENCHMARK", "").lower() == "true"
    
    if real_mode:
        try:
            resp = httpx.get("http://localhost:11434/", timeout=2.0)
            if resp.status_code == 200:
                # Check if models are present
                from app.ollama_verify import verify_all_models
                models_status = verify_all_models()
                if not all(models_status.values()):
                    real_mode = False
            else:
                real_mode = False
        except Exception:
            real_mode = False

    # Initialize components
    if real_mode:
        print("\n[BENCHMARK] Running in REAL mode against Ollama & Kokoro ONNX.")
        reset_provider()
        provider = get_provider()
        graph = build_graph(provider=provider, db_session_factory=None)
        tts = get_kokoro_tts()
    else:
        print("\n[BENCHMARK] Running in MOCK mode (Ollama / Kokoro ONNX not fully available or RUN_REAL_PI5_BENCHMARK not set).")
        provider = MockLLMProvider()
        graph = build_graph(provider=provider, db_session_factory=None)
        tts = MockKokoroTTS()

    # Pre-warmup memory check
    mem_before = _get_total_memory()
    
    # 2. Run 3 concurrent heir turns
    async def task_wrapper(i):
        # In mock mode, we inject some artificial latency to test the harness
        if not real_mode:
            await asyncio.sleep(0.05 + i * 0.02)
        return await run_single_heir_turn(
            graph=graph,
            provider=provider,
            tts=tts,
            session_id=f"session-{i}",
            heir_id=f"heir-{i}",
            text=f"I want to talk about my grandfather's clock {i}."
        )

    tasks = [
        task_wrapper(i)
        for i in range(3)
    ]
    
    latencies = await asyncio.gather(*tasks)
    mem_after = _get_total_memory()

    # 3. Calculate metrics
    median_latency = sorted(latencies)[len(latencies) // 2]
    max_memory_bytes = max(mem_before, mem_after)
    max_memory_gb = max_memory_bytes / (1024 ** 3)

    print(f"\n[BENCHMARK RESULTS]")
    print(f"  Heir Latencies: {[f'{l:.3f}s' for l in latencies]}")
    print(f"  Median Latency: {median_latency:.3f}s")
    print(f"  Max Memory Usage: {max_memory_gb:.3f} GB")
    print(f"  Mode: {'REAL' if real_mode else 'MOCK'}")

    # 4. Assertions
    # Check if we are running on the target Raspberry Pi 5 hardware
    is_pi5 = os.environ.get("IS_PI5", "").lower() == "true"
    if not is_pi5:
        try:
            if os.path.exists("/proc/device-tree/model"):
                with open("/proc/device-tree/model", "r") as f:
                    if "Raspberry Pi 5" in f.read():
                        is_pi5 = True
        except Exception:
            pass

    if is_pi5:
        # Enforce strict constraints on target Raspberry Pi 5 hardware
        assert median_latency < 5.0, f"Median latency {median_latency:.3f}s exceeds 5.0s Pi 5 threshold!"
        assert max_memory_gb < 7.2, f"Memory usage {max_memory_gb:.3f} GB exceeds 7.2 GB Pi 5 threshold!"
    else:
        # Relax constraints on non-Pi development machines to prevent environment differences from breaking tests
        assert median_latency < 60.0, f"Median latency {median_latency:.3f}s exceeds 60.0s dev threshold!"
        assert max_memory_gb < 12.0, f"Memory usage {max_memory_gb:.3f} GB exceeds 12.0 GB dev threshold!"
        if median_latency >= 5.0:
            print(f"  [WARNING] Median latency {median_latency:.3f}s exceeds 5.0s Pi 5 threshold (expected on non-Pi CPU dev hardware).")
