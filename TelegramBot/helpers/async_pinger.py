"""
Advanced Asynchronous Ping Module
---------------------------------

A robust, production-grade asynchronous ping module that checks if bots are alive
with configurable retry mechanisms, timeouts, and logging.

Features:
- Asynchronous bot checking with controlled concurrency
- Configurable retry mechanism with exponential backoff
- Detailed logging and reporting
- Timeout handling
- HTTP status code validation
- Custom callback support
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, List, Optional, Union, Any
import aiohttp
from aiohttp.client_exceptions import (
    ClientConnectorError, 
    ClientOSError,
    ServerDisconnectedError,
    ClientResponseError,
    TooManyRedirects,
    ClientPayloadError,
    ClientError
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("async_ping")

class PingStatus(Enum):
    """Enum representing the status of a ping operation."""
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    ERROR = "error"
    RETRY = "retry"


@dataclass
class PingResult:
    """Data class representing the result of a ping operation."""
    url: str
    status: PingStatus
    status_code: Optional[int] = None
    response_time: Optional[float] = None
    retry_count: int = 0
    error: Optional[Exception] = None
    timestamp: float = time.time()
    response_data: Optional[Any] = None

    def is_success(self) -> bool:
        """Check if ping was successful."""
        return self.status == PingStatus.SUCCESS

    def to_dict(self) -> Dict:
        """Convert result to dictionary."""
        return {
            "url": self.url,
            "status": self.status.value,
            "status_code": self.status_code,
            "response_time_ms": round(self.response_time * 1000) if self.response_time else None,
            "retry_count": self.retry_count,
            "error": str(self.error) if self.error else None,
            "timestamp": self.timestamp,
        }


class AsyncPinger:
    """
    Asynchronous ping module for checking if bots are alive.
    
    This class provides methods to ping webbots asynchronously with a configurable
    retry mechanism and detailed reporting.
    """
    
    def __init__(
        self,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        retry_backoff_factor: float = 1.5,
        timeout: float = 5.0,
        concurrent_limit: int = 10,
        valid_status_codes: List[int] = None,
        headers: Dict[str, str] = None,
        on_success: Optional[Callable[[PingResult], None]] = None,
        on_failure: Optional[Callable[[PingResult], None]] = None,
        on_retry: Optional[Callable[[PingResult], None]] = None,
        session: Optional[aiohttp.ClientSession] = None,
    ):
        """
        Initialize AsyncPinger with configuration options.
        
        Args:
            max_retries: Maximum number of retry attempts (default: 3)
            retry_delay: Initial delay between retries in seconds (default: 1.0)
            retry_backoff_factor: Multiplier for exponential backoff (default: 1.5)
            timeout: Request timeout in seconds (default: 5.0)
            concurrent_limit: Maximum number of concurrent requests (default: 10)
            valid_status_codes: List of status codes considered valid (default: [200])
            headers: Custom HTTP headers to send with requests
            on_success: Callback function for successful pings
            on_failure: Callback function for failed pings
            on_retry: Callback function called before a retry attempt
            session: Optional aiohttp session to use instead of creating a new one
        """
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.retry_backoff_factor = retry_backoff_factor
        self.timeout = timeout
        self.concurrent_limit = concurrent_limit
        self.valid_status_codes = valid_status_codes or [200]
        self.headers = headers or {
            "User-Agent": "AsyncPinger/1.0",
            "Accept": "*/*",
        }
        self.on_success = on_success
        self.on_failure = on_failure
        self.on_retry = on_retry
        self._session = session
        self._semaphore = None  # Will be initialized in ping_multiple
        self._own_session = False
        
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp client session."""
        if self._session is None or self._session.closed:
            logger.debug("(async ping) Creating new session")
            self._session = aiohttp.ClientSession(headers=self.headers)
            self._own_session = True
        return self._session
    
    async def _close_session(self) -> None:
        """Close the aiohttp client session if it was created by this instance."""
        if self._own_session and self._session and not self._session.closed:
            logger.debug("(async ping) Closing session")
            await self._session.close()
            self._session = None
            self._own_session = False
    
    def _calculate_retry_delay(self, retry_count: int) -> float:
        """Calculate the delay before the next retry attempt using exponential backoff."""
        return self.retry_delay * (self.retry_backoff_factor ** retry_count)
    
    async def ping(self, url: str, retry_count: int = 0) -> PingResult:
        """
        Ping a single URL and return the result.
        
        Args:
            url: The URL to ping
            retry_count: Current retry attempt (used internally)
            
        Returns:
            PingResult: Object containing the result of the ping operation
        """
        if not url.startswith(('http://', 'https://')):
            url = f"https://{url}"
            
        start_time = time.time()
        
        try:
            session = await self._get_session()
            if session is None or session.closed:
              logger.error(f"Session invalid for {url}, recreating...")
              self._session = None  # Force recreation
              session = await self._get_session()
            
            async with session.get(
                url, 
                timeout=self.timeout,
                allow_redirects=True
            ) as response:
                response_time = time.time() - start_time
                
                if response.status in self.valid_status_codes:
                    result = PingResult(
                        url=url,
                        status=PingStatus.SUCCESS,
                        status_code=response.status,
                        response_time=response_time,
                        retry_count=retry_count
                    )
                    logger.info(f"Successfully pinged {url} (status: {response.status}, time: {response_time:.2f}s)")
                    
                    if self.on_success:
                        self.on_success(result)
                        
                    return result
                else:
                    error_msg = f"Invalid status code: {response.status}"
                    logger.warning(f"Failed to ping {url}: {error_msg}")
                    
                    if retry_count < self.max_retries:
                        retry_delay = self._calculate_retry_delay(retry_count)
                        retry_result = PingResult(
                            url=url,
                            status=PingStatus.RETRY,
                            status_code=response.status,
                            response_time=response_time,
                            retry_count=retry_count,
                            error=ClientResponseError(
                                request_info=response.request_info,
                                history=response.history,
                                status=response.status,
                                message=error_msg,
                                headers=response.headers
                            )
                        )
                        
                        if self.on_retry:
                            self.on_retry(retry_result)
                            
                        logger.info(f"Retrying {url} in {retry_delay:.2f}s (attempt {retry_count + 1}/{self.max_retries})")
                        await asyncio.sleep(retry_delay)
                        return await self.ping(url, retry_count + 1)
                    else:
                        failure_result = PingResult(
                            url=url,
                            status=PingStatus.FAILURE,
                            status_code=response.status,
                            response_time=response_time,
                            retry_count=retry_count,
                            error=ClientResponseError(
                                request_info=response.request_info,
                                history=response.history,
                                status=response.status,
                                message=error_msg,
                                headers=response.headers
                            )
                        )
                        
                        if self.on_failure:
                            self.on_failure(failure_result)
                            
                        return failure_result
                        
        except asyncio.TimeoutError:
            response_time = time.time() - start_time
            logger.warning(f"Timeout while pinging {url} after {response_time:.2f}s")
            
            if retry_count < self.max_retries:
                retry_delay = self._calculate_retry_delay(retry_count)
                retry_result = PingResult(
                    url=url,
                    status=PingStatus.RETRY,
                    response_time=response_time,
                    retry_count=retry_count,
                    error=asyncio.TimeoutError(f"Request timed out after {self.timeout}s")
                )
                
                if self.on_retry:
                    self.on_retry(retry_result)
                    
                logger.info(f"Retrying {url} in {retry_delay:.2f}s (attempt {retry_count + 1}/{self.max_retries})")
                await asyncio.sleep(retry_delay)
                return await self.ping(url, retry_count + 1)
            else:
                timeout_result = PingResult(
                    url=url,
                    status=PingStatus.TIMEOUT,
                    response_time=response_time,
                    retry_count=retry_count,
                    error=asyncio.TimeoutError(f"Request timed out after {self.timeout}s")
                )
                
                if self.on_failure:
                    self.on_failure(timeout_result)
                    
                return timeout_result
                
        except (
            ClientConnectorError,
            ClientOSError,
            ServerDisconnectedError,
            TooManyRedirects,
            ClientPayloadError,
            ClientError
        ) as e:
            response_time = time.time() - start_time
            logger.warning(f"Error while pinging {url}: {str(e)}")
            
            if retry_count < self.max_retries:
                retry_delay = self._calculate_retry_delay(retry_count)
                retry_result = PingResult(
                    url=url,
                    status=PingStatus.RETRY,
                    response_time=response_time,
                    retry_count=retry_count,
                    error=e
                )
                
                if self.on_retry:
                    self.on_retry(retry_result)
                    
                logger.info(f"Retrying {url} in {retry_delay:.2f}s (attempt {retry_count + 1}/{self.max_retries})")
                await asyncio.sleep(retry_delay)
                return await self.ping(url, retry_count + 1)
            else:
                error_result = PingResult(
                    url=url,
                    status=PingStatus.ERROR,
                    response_time=response_time,
                    retry_count=retry_count,
                    error=e
                )
                
                if self.on_failure:
                    self.on_failure(error_result)
                    
                return error_result
        
        except Exception as e:
            response_time = time.time() - start_time
            logger.error(f"Unexpected error while pinging {url}: {str(e)}")
            
            error_result = PingResult(
                url=url,
                status=PingStatus.ERROR,
                response_time=response_time,
                retry_count=retry_count,
                error=e
            )
            
            if self.on_failure:
                self.on_failure(error_result)
                
            return error_result

    async def ping_multiple(self, urls: List[str], sequential: bool = False) -> List[PingResult]:
      """
      Ping multiple URLs and return their results.
      
      Args:
          urls: List of URLs to ping
          sequential: If True, ping URLs one by one; if False, ping concurrently
                      with limit set by concurrent_limit (default: False)
      
      Returns:
          List[PingResult]: List of ping results
      """
      self._semaphore = asyncio.Semaphore(1 if sequential else self.concurrent_limit)
      
      async def _ping_with_semaphore(url):
          async with self._semaphore:
              return await self.ping(url)
      
      tasks = [_ping_with_semaphore(url) for url in urls]
      results = await asyncio.gather(*tasks, return_exceptions=True)
      
      # Convert exceptions to PingResult objects
      processed_results = []
      for i, result in enumerate(results):
          if isinstance(result, Exception):
              processed_results.append(
                  PingResult(
                      url=urls[i],
                      status=PingStatus.ERROR,
                      error=result
                  )
              )
          else:
              processed_results.append(result)
      
      return processed_results
        
    async def close(self):
        if self._session is not None and not self._session.closed:
            await self._session.close()
            self._session = None
            
            
    async def ping_sequential(self, urls: List[str]) -> List[PingResult]:
        """
        Ping multiple URLs sequentially, one by one.
        
        Args:
            urls: List of URLs to ping
            
        Returns:
            List[PingResult]: List of ping results
        """
        return await self.ping_multiple(urls, sequential=True)


# Example usage
async def main():
    # Basic example
    pinger = AsyncPinger(
        max_retries=3,
        retry_delay=2.0,
        timeout=10.0,
        valid_status_codes=[200, 201, 204]
    )
    
    # Define callbacks
    def on_success(result):
        print(f"✓ {result.url} is alive! Response time: {result.response_time:.2f}s")
    
    def on_failure(result):
        print(f"✗ {result.url} failed after {result.retry_count} retries: {result.error}")
    
    # Create pinger with callbacks
    advanced_pinger = AsyncPinger(
        max_retries=2,
        retry_delay=1.5,
        retry_backoff_factor=2.0,
        timeout=5.0,
        concurrent_limit=5,
        valid_status_codes=[200, 201, 202, 204],
        on_success=on_success,
        on_failure=on_failure
    )
    
    # List of bots to check
    bots = [
        "https://animeosint-telgram.onrender.com",
        "https://spotify-downloader-wwv2.onrender.com/alive",
        "https://www.nonexistentwebbotabc123.com",
        "https://instagram-downloader-eb13.onrender.com",
        "https://ares-tgbot-3.onrender.com/alive"
    ]
    
    # Ping bots concurrently
    print("\nPinging bots concurrently:")
    results = await advanced_pinger.ping_multiple(bots)
    
    # Print summary
    print("\nSummary:")
    success_count = sum(1 for r in results if r.is_success())
    print(f"Success: {success_count}/{len(bots)}")
    print(f"Failed: {len(bots) - success_count}/{len(bots)}")
    
    # Ping bots sequentially
    print("\nPinging bots sequentially:")
    sequential_results = await advanced_pinger.ping_sequential(bots)
    
    # Print sequential summary
    print("\nSequential Summary:")
    success_count = sum(1 for r in sequential_results if r.is_success())
    print(f"Success: {success_count}/{len(bots)}")
    print(f"Failed: {len(bots) - success_count}/{len(bots)}")


if __name__ == "__main__":
    asyncio.run(main())