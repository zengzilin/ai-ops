from __future__ import annotations

import logging
import asyncio
import threading
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

from app.core.config import SETTINGS
from app.utils.http_client import http_post

logger = logging.getLogger(__name__)

# Thread pool for async notifications
_notification_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="notify")


def _truncate(text: str, max_len: int = 1800) -> str:
    """Truncate text to max length"""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def notify_dingtalk(text: str) -> None:
    """Send notification to DingTalk"""
    if not SETTINGS.dingtalk_webhook:
        logger.debug("DingTalk webhook not configured")
        return
    
    try:
        payload = {"msgtype": "text", "text": {"content": _truncate(text)}}
        status, response = http_post(SETTINGS.dingtalk_webhook, json=payload, timeout=10)
        if status < 300:
            logger.info("DingTalk notification sent successfully")
        else:
            logger.error(f"DingTalk notification failed: {status} {response}")
    except Exception as e:
        logger.error(f"DingTalk notification error: {e}")


def notify_feishu(text: str) -> None:
    """Send notification to Feishu"""
    if not SETTINGS.feishu_webhook:
        logger.debug("Feishu webhook not configured")
        return
    
    try:
        payload = {"msg_type": "text", "content": {"text": _truncate(text)}}
        status, response = http_post(SETTINGS.feishu_webhook, json=payload, timeout=10)
        if status < 300:
            logger.info("Feishu notification sent successfully")
        else:
            logger.error(f"Feishu notification failed: {status} {response}")
    except Exception as e:
        logger.error(f"Feishu notification error: {e}")


def notify_slack(text: str) -> None:
    """Send notification to Slack"""
    if not SETTINGS.slack_webhook:
        logger.debug("Slack webhook not configured")
        return
    
    try:
        payload = {"text": _truncate(text)}
        status, response = http_post(SETTINGS.slack_webhook, json=payload, timeout=10)
        if status < 300:
            logger.info("Slack notification sent successfully")
        else:
            logger.error(f"Slack notification failed: {status} {response}")
    except Exception as e:
        logger.error(f"Slack notification error: {e}")


def notify_workwechat(text: str) -> None:
    """Send notification to Enterprise WeChat (企业微信)"""
    if not SETTINGS.workwechat_url:
        logger.debug("Enterprise WeChat URL not configured")
        return
    
    try:
        payload = {
            "channel": SETTINGS.workwechat_channel,
            "content": _truncate(text)
        }
        status, response = http_post(SETTINGS.workwechat_url, json=payload, timeout=10)
        if status < 300:
            logger.info("Enterprise WeChat notification sent successfully")
        else:
            logger.error(f"Enterprise WeChat notification failed: {status} {response}")
    except Exception as e:
        logger.error(f"Enterprise WeChat notification error: {e}")


def notify_all(text: str) -> None:
    """Send notification to all configured channels"""
    logger.info(f"Sending notification to all channels: {text[:100]}...")
    
    # Submit notifications to thread pool for async execution
    futures = []
    futures.append(_notification_executor.submit(notify_dingtalk, text))
    futures.append(_notification_executor.submit(notify_feishu, text))
    futures.append(_notification_executor.submit(notify_slack, text))
    futures.append(_notification_executor.submit(notify_workwechat, text))
    
    # Wait for all notifications to complete (with timeout)
    for future in futures:
        try:
            future.result(timeout=30)  # 30 second timeout per notification
        except Exception as e:
            logger.error(f"Notification future failed: {e}")


def shutdown_notifications() -> None:
    """Shutdown notification thread pool"""
    logger.info("Shutting down notification thread pool")
    _notification_executor.shutdown(wait=True)


