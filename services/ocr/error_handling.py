import logging
import asyncio
from typing import Dict, Any, List, Type
from dataclasses import dataclass
from enum import Enum

from services.interfaces import IErrorHandler

logger = logging.getLogger(__name__)

class ErrorType(Enum):
    NETWORK_ERROR = "network"
    RATE_LIMIT_ERROR = "rate_limit"
    AUTHENTICATION_ERROR = "auth"
    PROCESSING_ERROR = "processing"
    STORAGE_ERROR = "storage"
    UNKNOWN_ERROR = "unknown"

@dataclass
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    backoff_multiplier: float = 2.0
    jitter: bool = True

class SmartErrorHandler(IErrorHandler):
    """Intelligent error handler with context-aware retry logic"""
    
    def __init__(self):
        self.retry_policies = {
            ErrorType.NETWORK_ERROR: RetryPolicy(max_attempts=3, base_delay=5.0),
            ErrorType.RATE_LIMIT_ERROR: RetryPolicy(max_attempts=5, base_delay=30.0, max_delay=300.0),
            ErrorType.AUTHENTICATION_ERROR: RetryPolicy(max_attempts=1),  # Don't retry auth errors
            ErrorType.PROCESSING_ERROR: RetryPolicy(max_attempts=2, base_delay=10.0),
            ErrorType.STORAGE_ERROR: RetryPolicy(max_attempts=3, base_delay=2.0),
            ErrorType.UNKNOWN_ERROR: RetryPolicy(max_attempts=2, base_delay=5.0)
        }
        
        self.error_mapping = {
            # Network-related errors
            'aiohttp.ClientConnectorError': ErrorType.NETWORK_ERROR,
            'aiohttp.ClientTimeout': ErrorType.NETWORK_ERROR,
            'ConnectionResetError': ErrorType.NETWORK_ERROR,
            'TimeoutError': ErrorType.NETWORK_ERROR,
            
            # Rate limiting
            'aiohttp.ClientResponseError': self._check_rate_limit,
            
            # Authentication
            'azure.core.exceptions.ClientAuthenticationError': ErrorType.AUTHENTICATION_ERROR,
            
            # Processing errors
            'subprocess.TimeoutExpired': ErrorType.PROCESSING_ERROR,
            'FileNotFoundError': ErrorType.PROCESSING_ERROR,
            
            # Storage errors
            'azure.core.exceptions.ResourceNotFoundError': ErrorType.STORAGE_ERROR,
            'azure.core.exceptions.ServiceRequestError': ErrorType.STORAGE_ERROR,
        }
    
    async def handle_error(self, error: Exception, context: Dict[str, Any]) -> bool:
        """Handle error with appropriate strategy"""
        error_type = self._classify_error(error)
        attempt = context.get('attempt', 1)
        
        # Log the error with context
        self._log_error(error, error_type, context, attempt)
        
        # Check if we should retry
        if self.should_retry(error, attempt):
            retry_policy = self.retry_policies[error_type]
            delay = self._calculate_delay(retry_policy, attempt)
            
            logger.info(f"Retrying in {delay:.2f} seconds (attempt {attempt + 1}/{retry_policy.max_attempts})")
            await asyncio.sleep(delay)
            
            # Update attempt counter
            context['attempt'] = attempt + 1
            return True
        
        # No retry
        logger.error(f"Max retries exceeded for {error_type.value} error")
        return False
    
    def should_retry(self, error: Exception, attempt: int) -> bool:
        """Determine if operation should be retried"""
        error_type = self._classify_error(error)
        retry_policy = self.retry_policies[error_type]
        
        return attempt < retry_policy.max_attempts
    
    def _classify_error(self, error: Exception) -> ErrorType:
        """Classify error type for appropriate handling"""
        error_class_name = error.__class__.__name__
        full_error_name = f"{error.__class__.__module__}.{error_class_name}"
        
        # Try exact match first
        if full_error_name in self.error_mapping:
            mapping = self.error_mapping[full_error_name]
        elif error_class_name in self.error_mapping:
            mapping = self.error_mapping[error_class_name]
        else:
            return ErrorType.UNKNOWN_ERROR
        
        # Handle dynamic classification
        if callable(mapping):
            return mapping(error)
        
        return mapping
    
    def _check_rate_limit(self, error) -> ErrorType:
        """Check if HTTP error is rate limiting"""
        if hasattr(error, 'status') and error.status == 429:
            return ErrorType.RATE_LIMIT_ERROR
        elif hasattr(error, 'status') and error.status in [401, 403]:
            return ErrorType.AUTHENTICATION_ERROR
        else:
            return ErrorType.NETWORK_ERROR
    
    def _calculate_delay(self, policy: RetryPolicy, attempt: int) -> float:
        """Calculate delay for retry with exponential backoff"""
        delay = policy.base_delay * (policy.backoff_multiplier ** (attempt - 1))
        delay = min(delay, policy.max_delay)
        
        # Add jitter to prevent thundering herd
        if policy.jitter:
            import random
            jitter = random.uniform(0.8, 1.2)
            delay *= jitter
        
        return delay
    
    def _log_error(self, error: Exception, error_type: ErrorType, context: Dict[str, Any], attempt: int):
        """Log error with appropriate level and context"""
        document = context.get('document')
        processor = context.get('processor')
        
        context_info = []
        if document:
            context_info.append(f"document={document.metadata.document_name}")
        if processor:
            context_info.append(f"processor={processor}")
        
        context_str = f" ({', '.join(context_info)})" if context_info else ""
        
        if attempt == 1:
            logger.error(f"Error during processing{context_str}: {str(error)}", exc_info=True)
        else:
            logger.warning(f"Retry attempt {attempt} failed{context_str}: {str(error)}")

class CircuitBreaker:
    """Circuit breaker pattern for external service calls"""
    
    def __init__(self, failure_threshold: int = 5, timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
    
    async def call(self, func, *args, **kwargs):
        """Execute function with circuit breaker protection"""
        if self.state == "OPEN":
            if self._should_attempt_reset():
                self.state = "HALF_OPEN"
            else:
                raise Exception("Circuit breaker is OPEN")
        
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise
    
    def _on_success(self):
        """Handle successful call"""
        self.failure_count = 0
        self.state = "CLOSED"
    
    def _on_failure(self):
        """Handle failed call"""
        import time
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.warning(f"Circuit breaker opened after {self.failure_count} failures")
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset"""
        import time
        return (
            self.last_failure_time and 
            time.time() - self.last_failure_time >= self.timeout
        )

class HealthCheck:
    """Health monitoring for services"""
    
    def __init__(self):
        self.service_status = {}
    
    async def check_service_health(self, service_name: str, health_check_func) -> bool:
        """Check health of a specific service"""
        try:
            await health_check_func()
            self.service_status[service_name] = {"status": "healthy", "last_check": self._now()}
            return True
        except Exception as e:
            self.service_status[service_name] = {
                "status": "unhealthy", 
                "error": str(e), 
                "last_check": self._now()
            }
            logger.error(f"Health check failed for {service_name}: {str(e)}")
            return False
    
    def get_overall_health(self) -> Dict[str, Any]:
        """Get overall system health status"""
        healthy_services = sum(1 for status in self.service_status.values() if status["status"] == "healthy")
        total_services = len(self.service_status)
        
        return {
            "overall_status": "healthy" if healthy_services == total_services else "degraded",
            "healthy_services": healthy_services,
            "total_services": total_services,
            "services": self.service_status
        }
    
    def _now(self):
        """Get current timestamp"""
        from datetime import datetime
        return datetime.utcnow().isoformat() 