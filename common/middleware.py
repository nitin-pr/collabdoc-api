import time


class RequestLoggingMiddleware:
    """Print HTTP method, path, status code and time taken for every request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.perf_counter()
        response = self.get_response(request)
        duration_ms = (time.perf_counter() - start) * 1000
        print(f'[API] {request.method} {request.path} -> {response.status_code} ({duration_ms:.2f} ms)')
        return response
