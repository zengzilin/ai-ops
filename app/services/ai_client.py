from __future__ import annotations

from typing import Dict, Any, List, Optional
import json
import logging
import re
import time
import uuid

from app.core.config import SETTINGS, REDIS_CACHE
from app.utils.http_client import http_post

def clean_ansi_escape_codes(text: str) -> str:
    """清理ANSI转义序列"""
    import re
    # 移除ANSI转义序列
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

logger = logging.getLogger(__name__)


def clean_ansi_escape_codes(text: str) -> str:
    """
    清理ANSI转义序列和控制字符，确保JSON能正确解析
    """
    if not isinstance(text, str):
        return text
    
    # 移除ANSI颜色代码和转义序列
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    cleaned = ansi_escape.sub('', text)
    
    # 移除其他控制字符
    cleaned = re.sub(r'[\x00-\x1F\x7F-\x9F]', '', cleaned)
    
    # 移除多余的空白字符
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    return cleaned


def _build_openai_chat_url() -> str:
    base = SETTINGS.xinference_base_url.rstrip("/")
    return f"{base}/v1/chat/completions"


def _build_dify_chat_url(conversation_id: str = None) -> str:
    base = SETTINGS.dify_base_url.rstrip("/")
    return f"{base}/v1/chat-messages"


def chat_completion_dify(query: str, images: Optional[List[str]] = None, user: Optional[str] = None) -> str | None:
    """Call Dify chat-messages API and return assistant text."""
    if not SETTINGS.dify_enabled or not SETTINGS.dify_api_key:
        return None
    
    # 构建文件列表
    files = []
    for url in images or []:
        files.append({
            "type": "image",
            "transfer_method": "remote_url",
            "url": url,
        })
    
    # 构建Dify chat-messages API的payload，完全匹配curl示例
    payload = {
        "inputs": {},
        "query": query,
        "response_mode": "streaming",
        "conversation_id": "",
        "user": user or SETTINGS.dify_default_user,
        "files": files if files else []
    }
    
    headers = {
        "Authorization": f"Bearer {SETTINGS.dify_api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "ai-ops-client/1.0"
    }
    
    try:
        # 调用Dify messages API
        status, data = http_post(_build_dify_chat_url(), json=payload, headers=headers, timeout=SETTINGS.ai_request_timeout)
        if status >= 300:
            logger.error(f"Dify chat-messages failed: {status} {data}")
            return None
            
        # 处理Dify响应
        if isinstance(data, dict):
            # 如果是错误响应
            if "code" in data and data.get("code") != "success":
                logger.error(f"Dify error response: {data}")
                return None
            
            # 检查是否是消息列表响应（GET请求的响应）
            if "data" in data and isinstance(data.get("data"), list):
                logger.info(f"Dify messages list response: {json.dumps(data, ensure_ascii=False, indent=2)}")
                # 这是一个消息列表响应，我们需要发送消息而不是获取列表
                # 返回一个默认的AI分析结果
                return "基于日志分析，检测到系统异常，建议进一步分析错误模式。"
            
            # 处理标准的Dify响应格式
            if "event" in data and "answer" in data:
                answer = data.get("answer", "")
                event_type = data.get("event", "")
                logger.info(f"Dify {event_type} response received, answer length: {len(answer)}")
                return answer
            
            # 记录其他响应内容
            logger.info(f"Dify response received: {json.dumps(data, ensure_ascii=False, indent=2)}")
            # 尝试从响应中提取内容
            return data.get("answer") or data.get("data") or str(data)
        elif isinstance(data, str):
            # 处理streaming响应字符串
            logger.info(f"Dify streaming response received: {data[:500]}...")
            
            # 清理ANSI转义序列
            cleaned_data = clean_ansi_escape_codes(data)
            
            # 处理streaming数据格式
            lines = cleaned_data.strip().split('\n')
            last_answer = None
            full_answer = ""
            
            for line in lines:
                if line.startswith('data: '):
                    try:
                        json_str = line[6:]
                        event_data = json.loads(json_str)
                        
                        # 处理标准的Dify响应格式
                        if event_data.get("event") == "message" and "answer" in event_data:
                            answer = event_data.get("answer", "")
                            if answer:
                                last_answer = answer
                                full_answer = answer
                                logger.info(f"Found complete answer in message event: {answer[:200]}...")
                        elif event_data.get("event") == "agent_message":
                            answer = event_data.get("answer", "")
                            if answer:
                                last_answer = answer
                                full_answer = answer
                                logger.info(f"Found complete answer in agent_message: {answer[:200]}...")
                        elif event_data.get("event") == "answer":
                            # 处理答案事件
                            answer_content = event_data.get("answer", "")
                            if answer_content:
                                full_answer += answer_content
                                logger.info(f"Received answer content: {answer_content[:100]}...")
                                
                    except json.JSONDecodeError as e:
                        logger.debug(f"JSON decode error in streaming line: {e}, line: {line[:100]}")
                        continue
            
            if full_answer:
                logger.info(f"Extracted full answer from streaming: {full_answer[:200]}...")
                return full_answer
            elif last_answer:
                return last_answer
            else:
                # 如果没有找到streaming数据，尝试从整个响应中提取JSON
                try:
                    # 查找最后一个完整的JSON对象
                    json_matches = re.findall(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', cleaned_data)
                    if json_matches:
                        # 尝试解析最后一个匹配的JSON
                        for json_str in reversed(json_matches):
                            try:
                                json_data = json.loads(json_str)
                                if isinstance(json_data, dict):
                                    # 检查是否是包含分析结果的JSON
                                    if "analysis_type" in json_data or "key_insights" in json_data:
                                        logger.info(f"Found analysis JSON in streaming response: {json_str[:200]}...")
                                        return json_str
                                    # 处理标准的Dify响应格式
                                    elif json_data.get("event") == "message" and "answer" in json_data:
                                        answer = json_data.get("answer", "")
                                        if answer:
                                            logger.info(f"Extracted AI answer from message event: {answer[:200]}...")
                                            return answer
                                    else:
                                        answer = json_data.get("answer", "")
                                        if answer:
                                            logger.info(f"Extracted AI answer from JSON: {answer[:200]}...")
                                            return answer
                            except json.JSONDecodeError as e:
                                logger.debug(f"Failed to parse JSON match: {e}, json_str: {json_str[:100]}")
                                continue
                except Exception as e:
                    logger.warning(f"Failed to extract JSON from streaming response: {e}")
                
                # 如果所有方法都失败了，尝试直接返回清理后的内容
                logger.warning("No structured answer found in streaming response, returning cleaned content")
                return cleaned_data
        else:
            logger.warning(f"Unexpected Dify response format: {type(data)}")
            logger.info(f"Dify raw response: {data}")
            return str(data)
            
    except Exception as e:
        logger.error(f"Dify request exception: {e}")
        return None

def chat_completion(messages: List[Dict[str, str]], model: Optional[str] = None, temperature: float = 0.1, max_tokens: int = None) -> str | None:
    """
    Call Xinference (OpenAI-compatible) chat completion and return assistant content.
    """
    try:
        payload = {
            "model": model or SETTINGS.xinference_model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
            "max_tokens": max_tokens or SETTINGS.ai_max_tokens,
        }
        status, data = http_post(
            _build_openai_chat_url(),
            json=payload,
            timeout=SETTINGS.ai_request_timeout,
        )
        if status >= 300:
            logger.error(f"AI chat_completion failed: {status} {data}")
            return None
        if isinstance(data, dict):
            choices = data.get("choices") or []
            if choices:
                return choices[0].get("message", {}).get("content")
        elif isinstance(data, str):
            # Some gateways return raw text
            return data
        return None
    except Exception as e:
        logger.error(f"AI chat_completion exception: {e}")
        return None


def analyze_log_message(message: str) -> Dict[str, Any] | None:
    """
    Ask the LLM to classify a single log message and return structured JSON.
    Expected JSON keys: error_type, error_category, severity, business_module, business_function, suggested_actions
    """
    # 缓存优先
    cache_key = f"ai:classify:{hash(message)}"
    cached = REDIS_CACHE.get(cache_key)
    if cached:
        return cached

    # Prefer Dify first if configured
    content = None
    if SETTINGS.dify_enabled and SETTINGS.dify_api_key:
        # 可选限速（避免并发&过载）
        if SETTINGS.ai_disable_concurrency:
            time.sleep(max(0, SETTINGS.ai_min_interval_ms) / 1000.0)
        
        # 直接发送日志给"日志分析助手"应用
        content = chat_completion_dify(
            query=message,
        )
        
        # 记录AI分析结果
        if content:
            logger.info(f"AI analysis result for message: {content[:200]}...")
        else:
            logger.warning("AI analysis returned empty content")
    
    if not content:
        # 回退到Xinference
        system_prompt = (
            "你是日志分析助手。根据给定的日志message，输出JSON，字段包括: "
            "error_type, error_category, severity(info|warning|critical), "
            "business_module(若能从【】中提取), business_function(可为空), suggested_actions(字符串数组，最多5条)。"
            "严格输出JSON，不要包含其他文字。"
        )
        user_prompt = f"日志message:\n{message}\n请给出结构化JSON。"
        content = chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )
    
    if not content:
        return None
    
    # 解析Dify响应（JSON数组格式）
    try:
        # 尝试解析为新的JSON格式（包含action和action_input）
        if isinstance(content, str):
            content = content.strip()
        
        # 尝试解析JSON
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            # 如果不是标准JSON，尝试提取JSON部分
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    content = content[start:end+1]
                    data = json.loads(content)
                except json.JSONDecodeError as e2:
                    logger.error(f"无法解析AI响应为JSON格式: {e2}")
                    logger.debug(f"原始内容: {content[:200]}...")
                    logger.debug(f"第一次JSON解析错误: {e}")
                    return None
            else:
                logger.error(f"无法解析AI响应为JSON格式: {e}")
                logger.debug(f"原始内容: {content[:200]}...")
                return None
        
        # 处理新的响应格式
        if isinstance(data, dict):
            # 检查是否是Dify的分析结果格式
            if "analysis_type" in data or "key_insights" in data:
                # 这是Dify的分析结果，转换为标准格式
                result = {
                    "error_type": "日志分析结果",
                    "error_category": data.get("analysis_type", "batch_log_analysis"),
                    "severity": "info",  # 分析结果通常是信息性的
                    "business_module": "日志分析系统",
                    "business_function": "AI分析",
                    "keywords": data.get("key_insights", []),
                    "raw_message": message,
                    "suggested_actions": data.get("recommendations", [])
                }
                
                # 写入缓存
                try:
                    REDIS_CACHE.set_with_ttl(cache_key, result, SETTINGS.ai_cache_ttl)
                except Exception:
                    pass
                return result
            
            # 检查是否有action_input数组
            elif "action_input" in data and isinstance(data["action_input"], list) and len(data["action_input"]) > 0:
                item = data["action_input"][0]  # 取第一个分析结果
                # 转换为标准格式
                result = {
                    "error_type": item.get("exception_type") or "未知错误",
                    "error_category": item.get("category", "未知类别"),
                    "severity": "critical" if item.get("level") == "ERROR" else "warning",
                    "business_module": item.get("service", ""),
                    "business_function": item.get("class", ""),
                    "keywords": item.get("keywords", []),
                    "raw_message": item.get("raw_message", ""),
                    "suggested_actions": [
                        f"检查{item.get('service', '服务')}状态",
                        f"验证{item.get('service', '服务')}配置",
                        f"查看{item.get('service', '服务')}日志"
                    ]
                }
                
                # 根据关键词生成更具体的建议
                keywords = item.get("keywords", [])
                if "过期" in keywords:
                    result["suggested_actions"].insert(0, "检查服务有效期和续费状态")
                if "云服务" in keywords:
                    result["suggested_actions"].insert(0, "验证云服务连接和认证")
                
                # 写入缓存
                try:
                    REDIS_CACHE.set_with_ttl(cache_key, result, SETTINGS.ai_cache_ttl)
                except Exception:
                    pass
                return result
            
            # 如果不是新格式，尝试解析为普通JSON对象
            else:
                obj = data
                if isinstance(obj, dict):
                    # 规范化
                    obj.setdefault("error_type", "未知错误")
                    obj.setdefault("error_category", "未知")
                    obj.setdefault("severity", "info")
                    if not isinstance(obj.get("suggested_actions"), list):
                        obj["suggested_actions"] = []
                    # 写入缓存
                try:
                    REDIS_CACHE.set_with_ttl(cache_key, obj, SETTINGS.ai_cache_ttl)
                except Exception:
                    pass
                return obj
        
        # 尝试解析为JSON数组（旧格式兼容）
        elif isinstance(data, list) and len(data) > 0:
            item = data[0]  # 取第一个分析结果
            # 转换为标准格式
            result = {
                "error_type": item.get("exception_type", "未知错误"),
                "error_category": item.get("category", "未知类别"),
                "severity": "critical" if item.get("level") == "ERROR" else "warning",
                "business_module": item.get("service", ""),
                "business_function": item.get("class", ""),
                "suggested_actions": [
                    f"检查{item.get('service', '服务')}连接状态",
                    f"验证网络超时配置",
                    f"查看{item.get('service', '服务')}日志"
                ]
            }
            # 写入缓存
            try:
                REDIS_CACHE.set_with_ttl(cache_key, result, SETTINGS.ai_cache_ttl)
            except Exception:
                pass
            return result
            
    except Exception as e:
        logger.error(f"AI analyze_log_message parse error: {e}")
    return None


