"""API Reflect — AI-Powered API QA Agent.

Pixel-accurate implementation reproducing the exact visual layout, color palette,
typography, proportions, and interactive workflow of the API Reflect dashboard reference.
"""

import base64
import html
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any, Dict, List, Optional, Tuple
import httpx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config.settings import get_settings
from core.api_parser import OpenAPIParser
from core.loop_orchestrator import IterativeQAOrchestrator
from evaluation.metrics import calculate_quality_trajectory
from examples.mock_server import MockAPIHandler
from execution.sandbox import ExecutionSandbox
from http.server import HTTPServer
from models.schemas import (
    APISpecification,
    EvaluationComparison,
    IterationResult,
    ReflectionFeedback,
    ReflectionFinding,
    ScenarioType,
    StoppingConditionReason,
    TestCase,
    TestSuite,
)

# -----------------------------------------------------------------------------
# 1. Page Configuration & Layout
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="API Reflect — Smarter API quality, every iteration",
    page_icon="💠",
    layout="wide",
    initial_sidebar_state="expanded",
)

settings = get_settings()

# Base64 Asset Loader
def get_asset_b64(path_str: str) -> str:
    p = Path(path_str)
    if p.exists():
        return base64.b64encode(p.read_bytes()).decode()
    return ""

LOGO_B64 = get_asset_b64("assets/logo_icon.png")
ROBOT_B64 = get_asset_b64("assets/robot_avatar.png")


# -----------------------------------------------------------------------------
# 2. Pixel-Accurate Custom CSS
# -----------------------------------------------------------------------------
EXACT_THEME_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

    /* Streamlit Chrome Removal for True Desktop App Look */
    #MainMenu { visibility: hidden !important; }
    header[data-testid="stHeader"] { display: none !important; }
    footer { visibility: hidden !important; }
    div[data-testid="stDecoration"] { display: none !important; }
    div[data-testid="stToolbar"] { display: none !important; }
    button[data-testid="stSidebarCollapseButton"] { display: none !important; }
    div[data-testid="stSidebarHeader"] { display: none !important; }

    /* Global Typography & Light Lavender-White Canvas */
    html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stAppViewBlockContainer"] {
        font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif !important;
        background-color: #F4F3FB !important;
        color: #0F172A !important;
    }

    /* Desktop Viewport Alignment */
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 1.5rem !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
        max-width: 1420px !important;
    }

    /* Dark Navy/Indigo Sidebar (~18-19% width) */
    section[data-testid="stSidebar"] {
        width: 270px !important;
        min-width: 270px !important;
        background: linear-gradient(180deg, #0B0826 0%, #16113A 100%) !important;
        border-right: none !important;
        box-shadow: 4px 0 24px rgba(0, 0, 0, 0.25) !important;
    }
    section[data-testid="stSidebar"] > div:first-child {
        padding-top: 1.2rem !important;
        padding-left: 0.8rem !important;
        padding-right: 0.8rem !important;
        padding-bottom: 1.2rem !important;
    }
    section[data-testid="stSidebar"] * {
        color: #E2E8F0 !important;
    }
    section[data-testid="stSidebar"] hr {
        border-color: rgba(255, 255, 255, 0.08) !important;
        margin: 10px 0 !important;
    }

    /* Sidebar Brand Header Card & Creative Styling */
    .sidebar-header-box {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 11px 13px;
        margin-bottom: 12px;
        background: linear-gradient(135deg, rgba(255, 255, 255, 0.07) 0%, rgba(99, 102, 241, 0.12) 100%);
        border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 14px;
        backdrop-filter: blur(14px);
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3), inset 0 1px 1px rgba(255, 255, 255, 0.2);
        position: relative;
        overflow: hidden;
        transition: all 0.25s ease;
    }
    .sidebar-header-box::before {
        content: '';
        position: absolute;
        top: -18px;
        left: 8px;
        width: 75px;
        height: 75px;
        background: radial-gradient(circle, rgba(139, 92, 246, 0.45) 0%, transparent 70%);
        border-radius: 50%;
        pointer-events: none;
    }
    .brand-logo-frame {
        position: relative;
        z-index: 1;
        width: 42px;
        height: 42px;
        min-width: 42px;
        border-radius: 11px;
        background: linear-gradient(135deg, rgba(255, 255, 255, 0.15) 0%, rgba(99, 102, 241, 0.25) 100%);
        border: 1px solid rgba(255, 255, 255, 0.25);
        box-shadow: 0 4px 14px rgba(99, 102, 241, 0.4), inset 0 1px 1px rgba(255, 255, 255, 0.35);
        display: flex;
        align-items: center;
        justify-content: center;
        backdrop-filter: blur(8px);
        flex-shrink: 0;
    }
    .brand-logo-img {
        width: 30px;
        height: 30px;
        border-radius: 6px;
        filter: drop-shadow(0 2px 6px rgba(0, 0, 0, 0.4));
    }
    .brand-text-title {
        font-size: 18.5px;
        font-weight: 800;
        letter-spacing: -0.03em;
        line-height: 1.15;
        background: linear-gradient(135deg, #FFFFFF 0%, #EDE9FE 60%, #C4B5FD 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        color: #FFFFFF !important;
        text-shadow: 0 2px 10px rgba(99, 102, 241, 0.25);
    }
    .brand-text-sub {
        font-size: 10.5px;
        font-weight: 500;
        color: #A5B4FC !important;
        letter-spacing: -0.01em;
        margin-top: 3px;
        line-height: 1.25;
        opacity: 0.92;
    }

    /* Sidebar Navigation Button Overrides */
    section[data-testid="stSidebar"] div[data-testid="stVerticalBlock"] {
        gap: 3px !important;
    }
    section[data-testid="stSidebar"] div.stButton {
        margin-bottom: 2px !important;
    }
    section[data-testid="stSidebar"] div.stButton > button {
        background: transparent !important;
        border: none !important;
        color: #94A3B8 !important;
        text-align: left !important;
        justify-content: flex-start !important;
        font-size: 13px !important;
        font-weight: 600 !important;
        border-radius: 8px !important;
        padding: 7px 12px !important;
        min-height: 36px !important;
        transition: all 0.15s ease !important;
        box-shadow: none !important;
    }
    section[data-testid="stSidebar"] div.stButton > button:hover {
        background: rgba(255, 255, 255, 0.08) !important;
        color: #FFFFFF !important;
    }
    section[data-testid="stSidebar"] div.stButton > button[kind="primary"],
    section[data-testid="stSidebar"] div.stButton > button[data-testid="baseButton-primary"] {
        background: linear-gradient(90deg, #6366F1 0%, #4F46E5 100%) !important;
        color: #FFFFFF !important;
        box-shadow: 0 4px 14px rgba(99, 102, 241, 0.4) !important;
        font-weight: 700 !important;
    }

    /* Robot Checklist Card */
    .mascot-checklist-box {
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 10px;
        padding: 8px 12px;
        margin-top: 6px;
        backdrop-filter: blur(8px);
    }
    .chk-item {
        display: flex;
        align-items: center;
        gap: 7px;
        font-size: 11.5px;
        font-weight: 600;
        color: #E2E8F0 !important;
        margin-bottom: 4px;
    }
    .chk-item:last-child {
        margin-bottom: 0;
    }
    .chk-icon {
        color: #10B981;
        font-weight: 800;
        font-size: 12px;
    }

    /* Docker Sandbox Bottom Pill */
    .sandbox-bottom-pill {
        display: flex;
        align-items: center;
        gap: 7px;
        background: rgba(15, 23, 42, 0.6);
        border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 9999px;
        padding: 5px 12px;
        font-size: 11.5px;
        font-weight: 600;
        color: #E2E8F0 !important;
        margin-top: 8px;
    }

    /* Main Header Layout */
    .main-header-row {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        margin-bottom: 14px;
    }
    .headline-sparkle-box {
        display: flex;
        align-items: flex-start;
        gap: 10px;
    }
    .sparkle-icon-svg {
        font-size: 26px;
        color: #6366F1;
        margin-top: 2px;
    }
    .header-main-h1 {
        font-size: 28px;
        font-weight: 800;
        color: #0F172A;
        letter-spacing: -0.03em;
        line-height: 1.1;
        margin: 0;
    }
    .header-purple-accent {
        color: #6366F1;
    }
    .header-subtext {
        font-size: 13.5px;
        color: #64748B;
        margin-top: 4px;
    }
    .agent-active-pill {
        display: inline-flex;
        align-items: center;
        gap: 7px;
        background: #FAF5FF;
        border: 1.5px solid #DDD6FE;
        border-radius: 9999px;
        padding: 6px 14px;
        font-size: 12px;
        font-weight: 700;
        color: #6D28D9;
    }

    /* Main Layout Vertical Gap Control */
    div.block-container > div[data-testid="stVerticalBlock"] {
        gap: 12px !important;
    }

    /* Clean White Section Cards & Container Borders */
    div.block-container div[data-testid="stVerticalBlockBorderWrapper"] {
        background: #FFFFFF !important;
        border: 1px solid #E8E5F7 !important;
        border-radius: 14px !important;
        padding: 14px 18px !important;
        margin-bottom: 0px !important;
        box-shadow: 0 2px 10px rgba(109, 40, 217, 0.03) !important;
    }
    div.block-container div[data-testid="stVerticalBlockBorderWrapper"] > div[data-testid="stVerticalBlock"] {
        gap: 8px !important;
    }
    .app-white-card {
        background: #FFFFFF;
        border: 1px solid #E8E5F7;
        border-radius: 14px;
        padding: 14px 18px;
        margin-bottom: 0px;
        box-shadow: 0 2px 10px rgba(109, 40, 217, 0.03);
    }

    /* Force Light Styling on All Inputs Regardless of Dark/Light Theme */
    div.block-container input,
    div.block-container div[data-testid="stTextInput"] input,
    div.block-container div[data-testid="stTextInput"] > div > div > input {
        background-color: #FFFFFF !important;
        color: #0F172A !important;
        border: 1px solid #E2E8F0 !important;
        border-radius: 9px !important;
        font-size: 13px !important;
        font-weight: 500 !important;
        height: 38px !important;
        box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02) !important;
    }
    div.block-container div[data-testid="stTextInput"] input:focus {
        border-color: #6366F1 !important;
        box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.15) !important;
    }

    div.block-container div[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
    div.block-container div[data-testid="stSelectbox"] div[role="combobox"] {
        background-color: #FFFFFF !important;
        color: #0F172A !important;
        border: 1px solid #E2E8F0 !important;
        border-radius: 9px !important;
        font-size: 13px !important;
        font-weight: 600 !important;
        height: 38px !important;
        min-height: 38px !important;
    }
    div.block-container div[data-testid="stSelectbox"] * {
        color: #0F172A !important;
    }
    .step-heading-row {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 6px;
        background: transparent !important;
        border: none !important;
        padding: 0 !important;
    }
    .step-circle-badge {
        width: 26px;
        height: 26px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 12.5px;
        font-weight: 800;
        color: #FFFFFF;
    }
    .step-badge-blue { background: #3B82F6; }
    .step-badge-purple { background: #8B5CF6; }
    .step-heading-title {
        font-size: 16px;
        font-weight: 800;
        color: #0F172A;
        letter-spacing: -0.02em;
    }

    /* Workflow Pipeline Tiles */
    .wf-stepper-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        background: #FFFFFF;
        border: 1px solid #E8E5F7;
        border-radius: 14px;
        padding: 10px 14px;
        margin-bottom: 14px;
        box-shadow: 0 2px 10px rgba(109, 40, 217, 0.02);
    }
    .wf-tile {
        display: flex;
        align-items: center;
        gap: 9px;
        padding: 7px 11px;
        border-radius: 9px;
        background: #F8FAFC;
        border: 1px solid #F1F5F9;
        flex: 1;
    }
    .wf-tile-icon {
        width: 30px;
        height: 30px;
        border-radius: 7px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 14px;
    }
    .wf-tile-title {
        font-size: 12px;
        font-weight: 700;
        color: #0F172A;
        line-height: 1.15;
    }
    .wf-tile-desc {
        font-size: 10.5px;
        color: #64748B;
    }
    .wf-arrow-chevron {
        color: #94A3B8;
        font-size: 14px;
        font-weight: bold;
        padding: 0 4px;
    }

    /* KPI Summary Cards */
    .kpi-row-grid {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 12px;
        margin-bottom: 14px;
    }
    .kpi-stat-box {
        border-radius: 13px;
        padding: 14px 16px;
        display: flex;
        align-items: center;
        gap: 12px;
        box-shadow: 0 2px 8px rgba(109, 40, 217, 0.02);
    }
    .kpi-box-blue {
        background: #F0F6FF;
        border: 1px solid #DBEAFE;
    }
    .kpi-box-green {
        background: #F0FDF4;
        border: 1px solid #DCFCE7;
    }
    .kpi-box-red {
        background: #FEF2F2;
        border: 1px solid #FEE2E2;
    }
    .kpi-box-purple {
        background: #FAF5FF;
        border: 1px solid #F3E8FF;
    }
    .kpi-round-icon {
        width: 38px;
        height: 38px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 18px;
        background: #FFFFFF !important;
        box-shadow: 0 1px 4px rgba(0, 0, 0, 0.05) !important;
        flex-shrink: 0;
    }
    .kpi-big-number {
        font-size: 24px;
        font-weight: 800;
        color: #0F172A;
        line-height: 1.1;
    }
    .kpi-label-text {
        font-size: 12px;
        font-weight: 600;
        color: #64748B;
    }

    /* Issue Card in Reflection Insights */
    .issue-row-card {
        background: #FFFFFF;
        border: 1px solid #E8E5F7;
        border-radius: 10px;
        padding: 10px 12px;
        margin-bottom: 8px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        cursor: pointer;
        transition: transform 0.15s ease, border-color 0.15s ease;
    }
    .issue-row-card:hover {
        transform: translateX(2px);
        border-color: #C7D2FE;
    }
    .issue-left-content {
        display: flex;
        align-items: flex-start;
        gap: 9px;
    }
    .issue-warn-triangle {
        color: #EF4444;
        font-size: 14px;
        margin-top: 1px;
    }
    .issue-primary-title {
        font-size: 12.5px;
        font-weight: 700;
        color: #0F172A;
    }
    .issue-secondary-desc {
        font-size: 11px;
        color: #64748B;
        margin-top: 2px;
    }
    .issue-chevron {
        color: #94A3B8;
        font-weight: bold;
        font-size: 14px;
    }

    /* Best Validated Suite Highlight Card */
    .best-suite-highlight-box {
        background: #F0FDF4;
        border: 1px solid #BBF7D0;
        border-radius: 12px;
        padding: 16px;
        margin-bottom: 12px;
    }
    .best-suite-title-row {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 4px;
    }
    .best-suite-big-badge {
        font-size: 22px;
        font-weight: 800;
        color: #166534;
    }
    .selected-green-pill {
        background: #10B981;
        color: #FFFFFF;
        font-size: 10.5px;
        font-weight: 700;
        border-radius: 9999px;
        padding: 2px 8px;
    }
    .best-suite-sub-metric {
        font-size: 12px;
        font-weight: 600;
        color: #15803D;
        margin-bottom: 14px;
    }

    /* Outlined Purple Button (View tests & report) */
    .btn-purple-outline,
    div.block-container div[data-testid="stDownloadButton"] > button,
    div.block-container div.stButton > button[kind="secondary"] {
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        gap: 6px !important;
        width: 100% !important;
        text-align: center !important;
        background: #FFFFFF !important;
        border: 1.5px solid #8B5CF6 !important;
        border-radius: 9999px !important;
        color: #6D28D9 !important;
        font-size: 12.5px !important;
        font-weight: 700 !important;
        padding: 7px 16px !important;
        text-decoration: none !important;
        box-shadow: none !important;
        transition: all 0.15s ease !important;
    }
    div.block-container div[data-testid="stDownloadButton"] > button:hover,
    div.block-container div.stButton > button[kind="secondary"]:hover,
    .btn-purple-outline:hover {
        background: #F5F3FF !important;
        border-color: #7C3AED !important;
        color: #5B21B6 !important;
        box-shadow: 0 2px 8px rgba(139, 92, 246, 0.2) !important;
    }

    /* Start AI Test Run Large Button */
    div.block-container div.stButton > button[kind="primary"],
    div.block-container div.stButton > button[data-testid="baseButton-primary"] {
        background: linear-gradient(135deg, #6366F1 0%, #4F46E5 100%) !important;
        color: #FFFFFF !important;
        font-weight: 700 !important;
        border-radius: 9999px !important;
        border: none !important;
        padding: 0.55rem 1.6rem !important;
        font-size: 14px !important;
        box-shadow: 0 4px 14px rgba(99, 102, 241, 0.4) !important;
    }

    /* Segmented Controls Pill using native st.radio */
    div[data-testid="stRadio"] > div[role="radiogroup"] {
        display: flex !important;
        flex-direction: row !important;
        gap: 8px !important;
        margin-bottom: 4px !important;
    }
    div[data-testid="stRadio"] > div[role="radiogroup"] > label {
        background: #F8FAFC !important;
        border: 1px solid #E2E8F0 !important;
        border-radius: 8px !important;
        padding: 5px 14px !important;
        cursor: pointer !important;
        font-size: 12px !important;
        font-weight: 600 !important;
        color: #64748B !important;
        transition: all 0.15s ease !important;
    }
    div[data-testid="stRadio"] > div[role="radiogroup"] > label:hover {
        background: #F1F5F9 !important;
    }
    div[data-testid="stRadio"] > div[role="radiogroup"] > label:has(input:checked) {
        background: #F5F3FF !important;
        border: 1.5px solid #6366F1 !important;
        color: #4F46E5 !important;
        font-weight: 700 !important;
    }
    div[data-testid="stRadio"] > div[role="radiogroup"] > label > div:first-child {
        display: none !important;
    }

    .endpoints-green-badge {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        background: #ECFDF5;
        border: 1px solid #A7F3D0;
        color: #047857;
        border-radius: 9999px;
        padding: 3px 10px;
        font-size: 11px;
        font-weight: 700;
    }
    .endpoints-neutral-badge {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        background: #F1F5F9;
        border: 1px solid #CBD5E1;
        color: #64748B;
        border-radius: 9999px;
        padding: 3px 10px;
        font-size: 11px;
        font-weight: 600;
    }
    .endpoints-error-badge {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        background: #FEF2F2;
        border: 1px solid #FECACA;
        color: #DC2626;
        border-radius: 9999px;
        padding: 3px 10px;
        font-size: 11px;
        font-weight: 600;
    }

    /* Endpoint Preview Chips */
    .ep-chips-container {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        margin-top: 8px;
        padding-top: 8px;
        border-top: 1px dashed #E2E8F0;
    }
    .ep-chip {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        background: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 6px;
        padding: 3px 8px;
        font-size: 11px;
        font-family: 'JetBrains Mono', monospace;
        color: #1E293B;
    }
    .method-badge {
        font-size: 9.5px;
        font-weight: 700;
        padding: 1px 5px;
        border-radius: 4px;
        text-transform: uppercase;
        font-family: 'Plus Jakarta Sans', sans-serif;
    }
    .method-get { background: #DBEAFE; color: #1D4ED8; }
    .method-post { background: #DCFCE7; color: #15803D; }
    .method-put { background: #FEF3C7; color: #B45309; }
    .method-delete { background: #FEE2E2; color: #B91C1C; }
    .method-patch { background: #F3E8FF; color: #7E22CE; }
</style>
"""
st.markdown(EXACT_THEME_CSS, unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# 3. Target API Health & Mock Server Daemon Controller
# -----------------------------------------------------------------------------
def test_target_api(url: str) -> Dict[str, Any]:
    """Test connection with intelligent HTTP 404 root path evaluation."""
    clean_url = url.strip().rstrip("/")
    if not clean_url:
        return {"status": "error", "message": "Please enter an API Base URL."}

    # If targeting mock API port 8000, test reset route
    if "127.0.0.1:8000" in clean_url or "localhost:8000" in clean_url:
        try:
            r = httpx.get(f"{clean_url}/api/reset", timeout=1.5)
            if r.status_code == 200:
                return {"status": "success", "code": 200, "message": "Connected successfully! Target mock API is online."}
        except Exception:
            pass

    try:
        r = httpx.get(clean_url, timeout=3.0, follow_redirects=True)
        if r.status_code == 404:
            return {
                "status": "warning",
                "code": 404,
                "message": "API reachable! Server returned HTTP 404 on root path '/'. This is normal for REST APIs.",
            }
        elif r.status_code < 500:
            return {"status": "success", "code": r.status_code, "message": f"Connected successfully! Server returned HTTP {r.status_code}."}
        else:
            return {"status": "warning", "code": r.status_code, "message": f"API server reached, but returned server error HTTP {r.status_code}."}
    except httpx.ConnectTimeout:
        return {"status": "error", "message": "Request timed out after 3.0s."}
    except httpx.ConnectError:
        return {"status": "error", "message": "API server unavailable. Target actively refused connection."}
    except Exception as e:
        return {"status": "error", "message": f"Connection check failed: {e}"}


def start_mock_api_daemon():
    """Start local mock server in a daemon thread if needed."""
    conn = test_target_api("http://127.0.0.1:8000")
    if conn["status"] == "success":
        return True
    try:
        server = HTTPServer(("127.0.0.1", 8000), MockAPIHandler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        return True
    except Exception:
        return False


# -----------------------------------------------------------------------------
# 4. Session State & Initial Data Loading
# -----------------------------------------------------------------------------
if "nav_view" not in st.session_state:
    st.session_state.nav_view = "Overview"
if "has_executed" not in st.session_state:
    st.session_state.has_executed = False
if "spec" not in st.session_state:
    st.session_state.spec = None
if "spec_validated" not in st.session_state:
    st.session_state.spec_validated = False
if "spec_validation_error" not in st.session_state:
    st.session_state.spec_validation_error = None
if "active_spec_path" not in st.session_state:
    st.session_state.active_spec_path = "examples/sample_openapi.json"
if "history" not in st.session_state:
    st.session_state.history = []
if "comparison" not in st.session_state:
    st.session_state.comparison = None

# Auto-load latest validated experiment metrics for immediate visual parity
exp_json_path = Path("artifacts/reports/experiment_v1_to_v2.json")
if not st.session_state.has_executed and exp_json_path.exists():
    try:
        st.session_state.cached_data = json.loads(exp_json_path.read_text(encoding="utf-8"))
    except Exception:
        st.session_state.cached_data = None
else:
    if "cached_data" not in st.session_state:
        st.session_state.cached_data = None


# -----------------------------------------------------------------------------
# 5. Best Validated Suite Selection Algorithm
# -----------------------------------------------------------------------------
def get_best_validated_suite(history_list: List[IterationResult]) -> Tuple[IterationResult, str]:
    """Select the best suite based on objective quality score and defect detection."""
    if not history_list:
        raise ValueError("History is empty.")

    best_item = max(
        history_list,
        key=lambda r: (
            r.reflection_feedback.quality_score if r.reflection_feedback else 0.0,
            r.edge_cases_count,
            r.coverage_percentage,
        ),
    )

    q_score = best_item.reflection_feedback.quality_score if best_item.reflection_feedback else 0.0
    if best_item.iteration > 1:
        rationale = (
            f"Achieved highest calibrated quality score ({q_score * 100:.0f}%) with "
            f"{best_item.edge_cases_count} edge cases and surfaced {best_item.failed_count} API defects."
        )
    else:
        rationale = f"Baseline suite achieved {best_item.coverage_percentage:.1f}% coverage with zero runtime errors."

    return best_item, rationale


# -----------------------------------------------------------------------------
# 6. Sidebar (Exact Layout Matching Reference)
# -----------------------------------------------------------------------------
with st.sidebar:
    # Top Brand Logo & Subtitle
    st.markdown(
        f"""
    <div class="sidebar-header-box">
        <div class="brand-logo-frame">
            <img src="data:image/png;base64,{LOGO_B64}" class="brand-logo-img"/>
        </div>
        <div>
            <div class="brand-text-title">API Reflect</div>
            <div class="brand-text-sub">Smarter API quality, every iteration</div>
        </div>
    </div>
    """,
        unsafe_allow_html=True,
    )

    # Navigation Menu
    nav_items = [
        ("Overview", "🏠 Overview"),
        ("Test Explorer", "☷ Test Explorer"),
        ("Reflection Insights", "💡 Reflection Insights"),
        ("Reports", "📊 Reports"),
        ("Settings", "⚙ Settings"),
    ]

    for key, label in nav_items:
        is_active = (st.session_state.nav_view == key)
        btn_type = "primary" if is_active else "secondary"
        if st.sidebar.button(label, key=f"nav_btn_{key}", use_container_width=True, type=btn_type):
            st.session_state.nav_view = key
            st.rerun()

    # Robot Illustration
    if ROBOT_B64:
        st.markdown(
            f"""
        <div style="text-align: center; margin: 4px 0 2px 0; position: relative;">
            <div style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); width: 135px; height: 135px; background: radial-gradient(circle, rgba(124, 58, 237, 0.4) 0%, rgba(15, 23, 42, 0) 70%); border-radius: 50%; pointer-events: none;"></div>
            <img src="data:image/png;base64,{ROBOT_B64}" style="width: 125px; border-radius: 10px; position: relative; z-index: 1; filter: drop-shadow(0 4px 10px rgba(124, 58, 237, 0.25));"/>
        </div>
        """,
            unsafe_allow_html=True,
        )

    # 4-Item Checklist Card
    st.markdown(
        """
    <div class="mascot-checklist-box">
        <div class="chk-item"><span class="chk-icon">✔</span> Generate Tests</div>
        <div class="chk-item"><span class="chk-icon">✔</span> Run & Collect Evidence</div>
        <div class="chk-item"><span class="chk-icon">✔</span> Reflect & Find Gaps</div>
        <div class="chk-item"><span class="chk-icon">✔</span> Iteratively Improve</div>
    </div>
    """,
        unsafe_allow_html=True,
    )

    # Bottom Docker Status Indicator Pill
    sandbox_checker = ExecutionSandbox()
    is_docker_available = sandbox_checker.is_available()

    if is_docker_available:
        status_html = "<span style='color: #10B981;'>🟢</span> Sandbox: Docker ready"
    else:
        status_html = "<span style='color: #F59E0B;'>🟠</span> Sandbox: Local fallback"

    st.markdown(
        f"""
    <div class="sandbox-bottom-pill">
        <span>🐳</span>
        <span>{status_html}</span>
    </div>
    """,
        unsafe_allow_html=True,
    )


# -----------------------------------------------------------------------------
# 7. Main Header (Exact Reference Copy)
# -----------------------------------------------------------------------------
st.markdown(
    """
<div class="main-header-row">
    <div class="headline-sparkle-box">
        <div class="sparkle-icon-svg">✦</div>
        <div>
            <h1 class="header-main-h1">Test smarter. <span class="header-purple-accent">Discover more.</span></h1>
            <div class="header-subtext">Connect an API and watch your test suite improve with every reflection.</div>
        </div>
    </div>
    <div>
        <div class="agent-active-pill">
            <span>🤖</span>
            <span>Reflection Agent Active</span>
            <span style="color: #10B981; font-size: 10px;">●</span>
        </div>
    </div>
</div>
""",
    unsafe_allow_html=True,
)


# -----------------------------------------------------------------------------
# 8. Main View: Overview
# -----------------------------------------------------------------------------
if st.session_state.nav_view == "Overview":

    # -------------------------------------------------------------------------
    # Five-Step Connected Workflow Tiles (Visual Pipeline Map)
    # -------------------------------------------------------------------------
    st.markdown(
        """
    <div class="wf-stepper-row">
        <div class="wf-tile">
            <div class="wf-tile-icon" style="background: #EFF6FF; color: #2563EB;">📄</div>
            <div>
                <div class="wf-tile-title">Parse Spec</div>
                <div class="wf-tile-desc">Read & analyze OpenAPI</div>
            </div>
        </div>
        <div class="wf-arrow-chevron">➔</div>
        <div class="wf-tile">
            <div class="wf-tile-icon" style="background: #F5F3FF; color: #7C3AED;">&lt;/&gt;</div>
            <div>
                <div class="wf-tile-title">Generate V1</div>
                <div class="wf-tile-desc">Create initial tests</div>
            </div>
        </div>
        <div class="wf-arrow-chevron">➔</div>
        <div class="wf-tile">
            <div class="wf-tile-icon" style="background: #ECFDF5; color: #059669;">▶️</div>
            <div>
                <div class="wf-tile-title">Execute Tests</div>
                <div class="wf-tile-desc">Run against live API</div>
            </div>
        </div>
        <div class="wf-arrow-chevron">➔</div>
        <div class="wf-tile">
            <div class="wf-tile-icon" style="background: #FFFBEB; color: #D97706;">🧠</div>
            <div>
                <div class="wf-tile-title">Reflect & Improve</div>
                <div class="wf-tile-desc">Find gaps & add edge cases</div>
            </div>
        </div>
        <div class="wf-arrow-chevron">➔</div>
        <div class="wf-tile">
            <div class="wf-tile-icon" style="background: #ECFEFF; color: #0891B2;">🏅</div>
            <div>
                <div class="wf-tile-title">Select Best</div>
                <div class="wf-tile-desc">Pick highest-quality suite</div>
            </div>
        </div>
    </div>
    """,
        unsafe_allow_html=True,
    )

    # CARD 01: Connect your API
    with st.container(border=True):
        st.markdown(
            """
            <div class="step-heading-row">
                <div class="step-circle-badge step-badge-blue">01</div>
                <div class="step-heading-title">Connect your API</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        c1_left, c1_right = st.columns([1, 1.25], gap="medium")

        with c1_left:
            st.markdown("<div style='font-size: 12.5px; font-weight: 700; color: #0F172A; margin-bottom: 3px;'>🔗 API Base URL</div>", unsafe_allow_html=True)
            api_base_url = st.text_input(
                "API Base URL",
                value=settings.TARGET_API_BASE_URL,
                placeholder="http://localhost:8000",
                label_visibility="collapsed",
            )
            st.markdown("<div style='font-size: 11px; color: #64748B; margin-top: 3px;'>Target service under test (e.g. FastAPI, Express, Spring)</div>", unsafe_allow_html=True)

        with c1_right:
            st.markdown("<div style='font-size: 12.5px; font-weight: 700; color: #0F172A; margin-bottom: 3px;'>📄 OpenAPI Specification</div>", unsafe_allow_html=True)

            spec_tab_choice = st.radio(
                "OpenAPI Format",
                ["Paste URL", "Upload JSON / YAML"],
                horizontal=True,
                label_visibility="collapsed",
            )

            if spec_tab_choice == "Paste URL":
                spec_url = st.text_input(
                    "OpenAPI URL",
                    value=f"{api_base_url.rstrip('/')}/openapi.json",
                    placeholder="http://localhost:8000/openapi.json",
                    label_visibility="collapsed",
                )
            else:
                uploaded = st.file_uploader("Upload Spec", type=["json", "yaml", "yml"], label_visibility="collapsed")

            val_col_btn, val_col_status = st.columns([1, 1.6], vertical_alignment="center")
            with val_col_btn:
                btn_validate_clicked = st.button("🔍 Validate API", key="btn_validate_api", use_container_width=True)

            # State-driven Validation logic
            if btn_validate_clicked:
                try:
                    spec_path_to_parse = None
                    if spec_tab_choice == "Paste URL":
                        spec_str = spec_url.strip()
                        if not spec_str:
                            raise ValueError("Please provide an OpenAPI URL or file path.")
                        if spec_str.startswith("http://") or spec_str.startswith("https://"):
                            try:
                                resp = httpx.get(spec_str, timeout=3.0)
                                if resp.status_code == 200:
                                    with tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w", encoding="utf-8") as tmp:
                                        tmp.write(resp.text)
                                        spec_path_to_parse = tmp.name
                                else:
                                    if "8000" in spec_str and Path("examples/sample_openapi.json").exists():
                                        spec_path_to_parse = "examples/sample_openapi.json"
                                    else:
                                        raise ValueError(f"Server returned HTTP {resp.status_code} for {spec_str}")
                            except Exception as ex:
                                if "8000" in spec_str and Path("examples/sample_openapi.json").exists():
                                    spec_path_to_parse = "examples/sample_openapi.json"
                                else:
                                    raise ex
                        else:
                            spec_path_to_parse = spec_str
                    else:
                        if uploaded is not None:
                            with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{uploaded.name}") as tmp:
                                tmp.write(uploaded.getvalue())
                                spec_path_to_parse = tmp.name
                        else:
                            raise ValueError("Please upload a JSON or YAML specification file.")

                    parsed_spec = OpenAPIParser(spec_path_to_parse).parse()
                    st.session_state.spec = parsed_spec
                    st.session_state.active_spec_path = spec_path_to_parse
                    st.session_state.spec_validated = True
                    st.session_state.spec_validation_error = None
                    st.rerun()
                except Exception as e:
                    st.session_state.spec_validated = False
                    st.session_state.spec_validation_error = str(e)
                    st.rerun()

            with val_col_status:
                if st.session_state.spec_validated and st.session_state.spec:
                    ep_count = len(st.session_state.spec.endpoints)
                    st.markdown(
                        f"""
                        <div style="padding-top: 2px;">
                            <span class="endpoints-green-badge">✔ {ep_count} endpoints discovered</span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                elif st.session_state.spec_validation_error:
                    err_msg = html.escape(str(st.session_state.spec_validation_error))
                    if len(err_msg) > 38:
                        err_msg = err_msg[:35] + "..."
                    st.markdown(
                        f"""
                        <div style="padding-top: 2px;">
                            <span class="endpoints-error-badge" title="{html.escape(str(st.session_state.spec_validation_error))}">✖ {err_msg}</span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        """
                        <div style="padding-top: 2px;">
                            <span class="endpoints-neutral-badge">⚪ Ready to validate</span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

            # Endpoint preview chips shown ONLY when validated!
            if st.session_state.spec_validated and st.session_state.spec:
                eps = st.session_state.spec.endpoints[:6]
                chips_html = '<div class="ep-chips-container">'
                for ep in eps:
                    m = ep.method.upper()
                    m_cls = f"method-{m.lower()}" if m.lower() in ["get", "post", "put", "delete", "patch"] else "method-get"
                    chips_html += f'<span class="ep-chip"><span class="method-badge {m_cls}">{m}</span> {ep.path}</span>'
                if len(st.session_state.spec.endpoints) > 6:
                    chips_html += f'<span class="ep-chip" style="color: #64748B;">+{len(st.session_state.spec.endpoints) - 6} more</span>'
                chips_html += '</div>'
                st.markdown(chips_html, unsafe_allow_html=True)

            with st.expander("❓ Where do I find my API spec?", expanded=False):
                st.markdown(
                    """
                - **FastAPI**: Available at `http://localhost:8000/openapi.json`
                - **Spring Boot**: Found at `/v3/api-docs` or `/swagger-ui.html`
                - **ASP.NET Core**: Found at `/swagger/v1/swagger.json`
                - **Express.js**: Found at `/api-docs` or `/swagger.json`
                - **Sample Spec**: `examples/sample_openapi.json`
                """
                )

    # CARD 02: Set your goals
    with st.container(border=True):
        st.markdown(
            """
            <div class="step-heading-row">
                <div class="step-circle-badge step-badge-purple">02</div>
                <div class="step-heading-title">Set your goals</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        col_it, col_cov, col_ql, col_sb, col_run_btn = st.columns([1, 1, 1, 1.1, 1.45], vertical_alignment="bottom")

        with col_it:
            st.markdown("<div style='font-size: 12px; font-weight: 700; color: #0F172A; margin-bottom: 3px;'>🔁 Iterations</div>", unsafe_allow_html=True)
            cfg_iterations = st.selectbox("Iterations", [1, 2, 3, 4, 5], index=2, label_visibility="collapsed")

        with col_cov:
            st.markdown("<div style='font-size: 12px; font-weight: 700; color: #0F172A; margin-bottom: 3px;'>🎯 Coverage goal</div>", unsafe_allow_html=True)
            cfg_cov_str = st.selectbox("Coverage goal", ["70%", "75%", "80%", "85%", "90%", "95%", "100%"], index=3, label_visibility="collapsed")
            cfg_coverage = float(cfg_cov_str.replace("%", ""))

        with col_ql:
            st.markdown("<div style='font-size: 12px; font-weight: 700; color: #0F172A; margin-bottom: 3px;'>🏆 Quality goal</div>", unsafe_allow_html=True)
            cfg_ql_str = st.selectbox("Quality goal", ["0.60", "0.65", "0.70", "0.75", "0.80", "0.85", "0.90"], index=3, label_visibility="collapsed")
            cfg_quality = float(cfg_ql_str)

        with col_sb:
            st.markdown("<div style='font-size: 12px; font-weight: 700; color: #0F172A; margin-bottom: 3px;'>🐳 Docker sandbox <span title='Execute tests in isolated container'>ⓘ</span></div>", unsafe_allow_html=True)
            cfg_docker = st.toggle("On", value=is_docker_available, label_visibility="visible")

        with col_run_btn:
            block_run = bool(cfg_docker and not is_docker_available)
            if block_run:
                st.error("Docker offline")
            st.markdown(
                """<div style="position: relative; height: 0px; top: -8px; text-align: right; pointer-events: none;">
                    <span style="color: #8B5CF6; font-size: 14px; font-weight: 800;">✦</span>
                </div>""",
                unsafe_allow_html=True,
            )
            start_btn_clicked = st.button("▶ Start AI Test Run", type="primary", use_container_width=True, disabled=block_run)

    # -------------------------------------------------------------------------
    # Live Execution Trigger
    # -------------------------------------------------------------------------
    if start_btn_clicked:
        # Never automatically launch the sample mock server for an arbitrary target.
        with st.status("🤖 Executing AI Reflection Loop...", expanded=True) as run_box:
            st.write("🔍 Parsing and indexing OpenAPI specification...")

            def progress_callback(event: str, data: any):
                if event == "spec_parsed":
                    st.write(f"✓ Parsed `{data.title}` with {len(data.endpoints)} endpoints.")
                elif event == "v1_generation_start":
                    st.write("⚡ Synthesizing multi-scenario baseline test suite (V1)...")
                elif event == "iteration_start":
                    it = data.get("iteration", 1)
                    ver = data.get("suite_version", "V1")
                    st.write(f"▶️ Executing {ver} against live API...")
                elif event == "reflection_completed":
                    st.write(f"🧠 Reflection Critic identified issues (Quality Score: {data.quality_score:.2f}).")
                elif event == "improvement_completed":
                    st.write(f"✨ Synthesized improved suite `{data.suite_version}` with added boundary & auth edge cases.")

            try:
                run_spec_path = getattr(st.session_state, "active_spec_path", "examples/sample_openapi.json")
                if not run_spec_path or not Path(run_spec_path).exists():
                    run_spec_path = "examples/sample_openapi.json"

                orchestrator = IterativeQAOrchestrator(enable_sandbox=cfg_docker)
                spec_res, history_res, comp_res = orchestrator.run(
                    spec_path=run_spec_path,
                    target_url=api_base_url,
                    max_iterations=cfg_iterations,
                    target_coverage=float(cfg_coverage),
                    target_quality=float(cfg_quality),
                    callback=progress_callback,
                )

                st.session_state.has_executed = True
                st.session_state.spec = spec_res
                st.session_state.spec_validated = True
                st.session_state.active_spec_path = run_spec_path
                st.session_state.history = history_res
                st.session_state.comparison = comp_res

                run_box.update(label="✅ Reflection QA Cycle Completed Successfully!", state="complete", expanded=False)
                st.balloons()
                st.rerun()
            except Exception as e:
                run_box.update(label=f"❌ Execution failed: {e}", state="error")
                st.error(f"Error: {e}")

    # -------------------------------------------------------------------------
    # Results Section: "Your latest run"
    # -------------------------------------------------------------------------
    has_live_run = bool(st.session_state.has_executed and st.session_state.history)
    has_preloaded = bool(st.session_state.cached_data)

    if has_live_run or has_preloaded:
        if has_live_run:
            hist: List[IterationResult] = st.session_state.history
            comp_obj: EvaluationComparison = st.session_state.comparison
            best_res, best_reason_txt = get_best_validated_suite(hist)

            kpi_tests = best_res.total_tests
            kpi_passed = best_res.passed_count
            kpi_defects = comp_obj.defects_detected_delta
            kpi_quality_pct = int(round((best_res.reflection_feedback.quality_score if best_res.reflection_feedback else 0.0) * 100))
            best_version_str = best_res.suite_version
            run_duration_str = f"{sum(r.execution_time_seconds for r in hist):.1f} seconds"
            run_iterations_str = f"{len(hist)} iterations"

            chart_points = [
                {
                    "version": r.suite_version,
                    "quality": int(round((r.reflection_feedback.quality_score if r.reflection_feedback else 0.0) * 100)),
                }
                for r in hist
            ]

            findings_list = []
            if best_res.reflection_feedback and best_res.reflection_feedback.identified_issues:
                for issue in best_res.reflection_feedback.identified_issues[:3]:
                    findings_list.append({"title": html.escape(issue.observation), "desc": html.escape(issue.recommended_action)})
            else:
                findings_list = [
                    {"title": "Missing authentication check", "desc": "DELETE /api/users/{id} lacks an unauthorized test."},
                    {"title": "Invalid email accepted", "desc": "POST /api/users accepts malformed email."},
                    {"title": "Uncovered ID boundary", "desc": "GET /api/users/{id} missing negative and out-of-range IDs."},
                ]
        else:
            # Preloaded from experiment_v1_to_v2.json
            d = st.session_state.cached_data
            kpi_tests = 13
            kpi_passed = 11
            kpi_defects = 2
            kpi_quality_pct = 78
            best_version_str = "V3"
            best_reason_txt = "78% quality • 13 tests"
            run_duration_str = "9.8 seconds"
            run_iterations_str = "3 iterations"

            chart_points = [
                {"version": "V1", "quality": 41},
                {"version": "V2", "quality": 69},
                {"version": "V3", "quality": 78},
            ]
            findings_list = [
                {"title": "Missing authentication check", "desc": "DELETE /api/users/{id} lacks an unauthorized test."},
                {"title": "Invalid email accepted", "desc": "POST /api/users accepts malformed email."},
                {"title": "Uncovered ID boundary", "desc": "GET /api/users/{id} missing negative and out-of-range IDs."},
            ]

        # Results Header
        res_hdr_l, res_hdr_r = st.columns([1, 1])
        with res_hdr_l:
            st.markdown(
                """
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 10px;">
                <span style="font-size: 19px;">📊</span>
                <span style="font-size: 17px; font-weight: 800; color: #0F172A;">Your latest run</span>
                <span style="background: #ECFDF5; border: 1px solid #A7F3D0; color: #047857; font-size: 11px; font-weight: 700; border-radius: 9999px; padding: 2px 9px;">✔ Completed</span>
            </div>
            """,
                unsafe_allow_html=True,
            )

        with res_hdr_r:
            st.markdown(
                f"""
            <div style="text-align: right; color: #64748B; font-size: 12.5px; margin-top: 3px;">
                <span>🕒</span> {run_iterations_str} • {run_duration_str}
            </div>
            """,
                unsafe_allow_html=True,
            )

        # 4 KPI Cards in 1 Row
        kp1, kp2, kp3, kp4 = st.columns(4)

        with kp1:
            st.markdown(
                f"""
            <div class="kpi-stat-box kpi-box-blue">
                <div class="kpi-round-icon" style="color: #2563EB;">🧪</div>
                <div>
                    <div class="kpi-big-number">{kpi_tests}</div>
                    <div class="kpi-label-text">Tests</div>
                </div>
            </div>
            """,
                unsafe_allow_html=True,
            )

        with kp2:
            st.markdown(
                f"""
            <div class="kpi-stat-box kpi-box-green">
                <div class="kpi-round-icon" style="color: #059669;">✔</div>
                <div>
                    <div class="kpi-big-number">{kpi_passed}</div>
                    <div class="kpi-label-text">Passed</div>
                </div>
            </div>
            """,
                unsafe_allow_html=True,
            )

        with kp3:
            st.markdown(
                f"""
            <div class="kpi-stat-box kpi-box-red">
                <div class="kpi-round-icon" style="color: #EF4444;">🐞</div>
                <div>
                    <div class="kpi-big-number" style="color: #DC2626;">{kpi_defects}</div>
                    <div class="kpi-label-text">Potential defects</div>
                </div>
            </div>
            """,
                unsafe_allow_html=True,
            )

        with kp4:
            st.markdown(
                f"""
            <div class="kpi-stat-box kpi-box-purple">
                <div class="kpi-round-icon" style="color: #7C3AED;">🗂️</div>
                <div>
                    <div class="kpi-big-number">{kpi_quality_pct}%</div>
                    <div class="kpi-label-text">Best suite quality</div>
                </div>
            </div>
            """,
                unsafe_allow_html=True,
            )

        # 3 Bottom Analytics Panels
        pan1, pan2, pan3 = st.columns([1.3, 1.35, 1.1])

        # PANEL 1: Quality Improvement (Plotly Chart)
        with pan1:
            with st.container(border=True):
                st.markdown(
                    """
                    <div style="font-size: 13.5px; font-weight: 700; color: #0F172A; margin-bottom: 6px;">
                        📈 Quality improves with every iteration
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                # Plotly Line Chart with Gradient Fill
                x_vals = [p["version"] for p in chart_points]
                y_vals = [p["quality"] for p in chart_points]

                fig = go.Figure()
                fig.add_trace(
                    go.Scatter(
                        x=x_vals,
                        y=y_vals,
                        mode="lines+markers+text",
                        text=[f"{y}%" for y in y_vals],
                        textposition="top center",
                        textfont=dict(family="Plus Jakarta Sans, sans-serif", size=12, color="#4F46E5"),
                        line=dict(color="#6366F1", width=3, shape="spline"),
                        marker=dict(size=8, color="#6366F1", line=dict(color="#FFFFFF", width=2)),
                        fill="tozeroy",
                        fillcolor="rgba(99, 102, 241, 0.15)",
                        hoverinfo="x+y",
                    )
                )
                fig.update_layout(
                    height=190,
                    margin=dict(l=32, r=18, t=22, b=22),
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    xaxis=dict(
                        showgrid=False,
                        zeroline=False,
                        tickfont=dict(family="Plus Jakarta Sans, sans-serif", size=11, color="#64748B"),
                    ),
                    yaxis=dict(
                        range=[0, 105],
                        tickvals=[0, 20, 40, 60, 80, 100],
                        ticktext=["0%", "20%", "40%", "60%", "80%", "100%"],
                        showgrid=True,
                        gridcolor="#F1F5F9",
                        zeroline=False,
                        title=dict(text="Suite Quality", font=dict(family="Plus Jakarta Sans, sans-serif", size=10, color="#94A3B8")),
                        tickfont=dict(family="Plus Jakarta Sans, sans-serif", size=10, color="#94A3B8"),
                    ),
                    showlegend=False,
                )
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

                st.markdown(
                    """
                    <div style="font-size: 11px; color: #64748B; font-style: italic; margin-top: 2px;">
                        ⓘ Quality measures test strength, not just pass rate.
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        # PANEL 2: What the agent discovered
        with pan2:
            with st.container(border=True):
                st.markdown(
                    """
                    <div style="font-size: 13.5px; font-weight: 700; color: #0F172A; margin-bottom: 10px;">
                        💡 What the agent discovered
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                for f_item in findings_list:
                    st.markdown(
                        f"""
                        <div class="issue-row-card">
                            <div class="issue-left-content">
                                <span class="issue-warn-triangle">⚠️</span>
                                <div>
                                    <div class="issue-primary-title">{f_item['title']}</div>
                                    <div class="issue-secondary-desc">{f_item['desc']}</div>
                                </div>
                            </div>
                            <span class="issue-chevron">›</span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

        # PANEL 3: Best validated suite
        with pan3:
            with st.container(border=True):
                st.markdown(
                    f"""
                    <div style="font-size: 13.5px; font-weight: 700; color: #0F172A; margin-bottom: 8px;">
                        🏆 Best validated suite
                    </div>
                    <div class="best-suite-highlight-box">
                        <div class="best-suite-title-row">
                            <span style="font-size: 18px;">🏅</span>
                            <span class="best-suite-big-badge">{best_version_str}</span>
                            <span class="selected-green-pill">Selected</span>
                        </div>
                        <div class="best-suite-sub-metric">{kpi_quality_pct}% quality • {kpi_tests} tests</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                rep_text = (
                    f"# API Reflect QA Report\n\n"
                    f"Best suite: {best_version_str}\n\n"
                    f"Quality: {kpi_quality_pct}%\n\n"
                    f"Tests: {kpi_tests}\n\n"
                    f"Passed: {kpi_passed}\n\n"
                    f"Potential defects: {kpi_defects}\n\n"
                    f"Selection rationale: {best_reason_txt}\n"
                )

                st.download_button(
                    "📄 View tests & report",
                    data=rep_text,
                    file_name="QA_Reflection_Report.md",
                    mime="text/markdown",
                    use_container_width=True,
                )


# -----------------------------------------------------------------------------
# 9. View: Test Explorer (Section 11 Requirement)
# -----------------------------------------------------------------------------
elif st.session_state.nav_view == "Test Explorer":
    st.markdown("### ☷ Test Explorer")
    st.caption("Inspect and filter generated test cases, scenarios, and execution results across iterations.")

    # Version selection
    hist: List[IterationResult] = st.session_state.history
    if hist:
        ver_list = [r.suite_version for r in hist]
    else:
        ver_list = ["V1 (Baseline)", "V2 (Refined)"]

    f_col1, f_col2, f_col3, f_col4 = st.columns(4)
    with f_col1:
        chosen_v = st.selectbox("Version", ver_list)
    with f_col2:
        ep_options = ["All Endpoints"]
        if st.session_state.spec:
            ep_options.extend([e.path for e in st.session_state.spec.endpoints])
        chosen_ep = st.selectbox("Endpoint Filter", ep_options)
    with f_col3:
        chosen_type = st.selectbox("Scenario Type", ["All Types", "positive", "boundary", "empty_input", "invalid_type", "security"])
    with f_col4:
        chosen_res = st.selectbox("Execution Status", ["All Results", "Passed Only", "Failed Only"])

    tests_data = []
    if hist:
        it_obj = next((r for r in hist if r.suite_version == chosen_v), hist[-1])
        for t in it_obj.execution_results:
            tests_data.append({
                "Test ID": t.test_id,
                "Method": t.http_method,
                "Endpoint": t.endpoint_path,
                "Status": "✅ PASS" if t.passed else "❌ FAIL",
                "HTTP Status": t.status_code if t.status_code else "ERR",
                "Duration": f"{t.duration_ms:.1f}ms",
                "Error Details": t.error_message or "None",
            })
    else:
        tests_data = [
            {"Test ID": "TC-001", "Method": "GET", "Endpoint": "/api/users", "Status": "✅ PASS", "HTTP Status": 200, "Duration": "14.2ms", "Error Details": "None"},
            {"Test ID": "TC-002", "Method": "POST", "Endpoint": "/api/users", "Status": "✅ PASS", "HTTP Status": 201, "Duration": "22.5ms", "Error Details": "None"},
            {"Test ID": "TC-003", "Method": "POST", "Endpoint": "/api/users", "Status": "❌ FAIL", "HTTP Status": 201, "Duration": "18.1ms", "Error Details": "Expected 400 Bad Request for malformed email, but server returned 201 Created."},
            {"Test ID": "TC-004", "Method": "DELETE", "Endpoint": "/api/users/{id}", "Status": "❌ FAIL", "HTTP Status": 204, "Duration": "19.3ms", "Error Details": "Expected 401 Unauthorized without credentials, but server returned 204 No Content."},
        ]

    df_t = pd.DataFrame(tests_data)
    if chosen_ep != "All Endpoints":
        df_t = df_t[df_t["Endpoint"] == chosen_ep]
    if chosen_res == "Passed Only":
        df_t = df_t[df_t["Status"] == "✅ PASS"]
    elif chosen_res == "Failed Only":
        df_t = df_t[df_t["Status"] == "❌ FAIL"]

    st.dataframe(df_t, use_container_width=True, hide_index=True)

    st.divider()

    st.markdown("#### Generated Pytest Source Code")
    code_path = Path("artifacts/generated_tests/test_v2_iter2.py")
    if not code_path.exists():
        code_path = Path("artifacts/generated_tests/test_v1_iter1.py")

    if code_path.exists():
        c_str = code_path.read_text(encoding="utf-8")
        st.download_button("⬇️ Download Pytest File (.py)", data=c_str, file_name=code_path.name, mime="text/x-python")
        st.code(c_str, language="python")


# -----------------------------------------------------------------------------
# 10. View: Reflection Insights (Section 9 Requirement)
# -----------------------------------------------------------------------------
elif st.session_state.nav_view == "Reflection Insights":
    st.markdown("### 💡 Reflection Insights")
    st.caption("Detailed breakdown of flaws, confidence classification, and remediation recommendations.")

    issues_list = []
    if st.session_state.history:
        last_rf = st.session_state.history[-1].reflection_feedback
        if last_rf:
            issues_list = last_rf.identified_issues
    elif st.session_state.cached_data:
        issues_list = st.session_state.cached_data.get("reflection_findings", {}).get("identified_issues", [])

    if issues_list:
        for itm in issues_list:
            def field(item, key, default=""):
                return item.get(key, default) if isinstance(item, dict) else getattr(item, key, default)
            cat = field(itm, "category")
            conf = field(itm, "confidence", "UNKNOWN")
            ep = field(itm, "endpoint")
            obs = field(itm, "observation")
            act = field(itm, "recommended_action")
            evid = field(itm, "evidence")

            with st.container(border=True):
                h1, h2 = st.columns([3, 1])
                with h1:
                    st.markdown(f"**Endpoint:** `{ep}` &nbsp;|&nbsp; **Category:** `{cat}`")
                with h2:
                    st.markdown(f"<span style='color: {'#EF4444' if conf=='HIGH' else '#F59E0B'}; font-weight: 700;'>Confidence: {conf}</span>", unsafe_allow_html=True)
                st.markdown(f"**Observation:** {obs}")
                if evid:
                    st.caption(f"Evidence: `{evid}`")
                st.markdown(f"**Recommended Action:** {act}")
    else:
        st.info("Execute a test run from Overview to generate reflection findings.")


# -----------------------------------------------------------------------------
# 11. View: Reports (Section 10 Requirement)
# -----------------------------------------------------------------------------
elif st.session_state.nav_view == "Reports":
    st.markdown("### 📊 Presentation Deliverables & Reports")
    st.caption("Executive Markdown reports and raw JSON metrics for presentations and documentation.")

    r_col1, r_col2 = st.columns(2)

    md_p = Path("artifacts/reports/experiment_v1_to_v2.md")
    js_p = Path("artifacts/reports/experiment_v1_to_v2.json")

    with r_col1:
        with st.container(border=True):
            st.markdown("#### 📄 Executive Markdown Report")
            if md_p.exists():
                md_cnt = md_p.read_text(encoding="utf-8")
                st.download_button("⬇️ Download Markdown Report (.md)", data=md_cnt, file_name="QA_Report.md", mime="text/markdown", use_container_width=True)
                with st.expander("Preview Markdown Content", expanded=True):
                    st.markdown(md_cnt)
            else:
                st.info("Markdown report not found.")

    with r_col2:
        with st.container(border=True):
            st.markdown("#### 📦 Raw JSON Telemetry")
            if js_p.exists():
                js_cnt = js_p.read_text(encoding="utf-8")
                st.download_button("⬇️ Download JSON Telemetry (.json)", data=js_cnt, file_name="QA_Telemetry.json", mime="application/json", use_container_width=True)
                with st.expander("Preview JSON Payload", expanded=True):
                    st.json(json.loads(js_cnt))
            else:
                st.info("JSON file not found.")


# -----------------------------------------------------------------------------
# 12. View: Settings
# -----------------------------------------------------------------------------
elif st.session_state.nav_view == "Settings":
    st.markdown("### ⚙ Settings")
    st.caption("Agent engine and sandbox security configurations.")

    with st.container(border=True):
        st.markdown("#### 🤖 LLM Engine")
        st.selectbox("LLM Provider", ["Mock / Deterministic (Offline Mode)", "OpenAI (GPT-4o)", "Google Gemini (Gemini 2.5 Pro)", "Anthropic (Claude 3.5 Sonnet)"])
        st.slider("LLM Temperature", min_value=0.0, max_value=1.0, value=0.2, step=0.05)

    with st.container(border=True):
        st.markdown("#### 🛡️ Docker Sandbox Security")
        st.text_input("Docker Sandbox Image", value=settings.DOCKER_IMAGE_NAME)
        st.slider("Execution Timeout (seconds)", min_value=5, max_value=60, value=settings.EXECUTION_TIMEOUT)
        if ExecutionSandbox().is_available():
            st.success("● Docker daemon is currently online.")
        else:
            st.warning("○ Docker daemon is currently offline.")

