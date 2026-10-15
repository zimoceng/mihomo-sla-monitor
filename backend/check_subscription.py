import getpass
import httpx
import yaml
url = getpass.getpass("订阅 URL: ").strip()

if not url.startswith(("https://", "http://")):
    raise ValueError("订阅 URL 必须以 https:// 或 http:// 开头")

try:
    with httpx.Client(
        proxy="http://127.0.0.1:7890",
        trust_env=False,
        follow_redirects=False,
        timeout=30
    ) as client:
        response = client.get(
            url,
            headers={
                "User-Agent": "clash.meta",
                "Accept": "application/yaml,text/yaml,*/*"
            }
        )

    print("HTTP 状态:", response.status_code)
    print("Content-Type:", response.headers.get("content-type"))
    print("响应大小:", len(response.content), "bytes")
    print("发生重定向:", response.is_redirect)

    if response.is_redirect:
        print("请检查订阅地址是否需要重定向")
    elif response.is_success:
        try:
            data = yaml.safe_load(response.text)

            if isinstance(data, dict):
                print("YAML 顶层字段:", list(data.keys()))
                proxies = data.get("proxies")
                print(
                    "proxies 节点数:",
                    len(proxies) if isinstance(proxies, list)
                    else "不存在"
                )
            elif isinstance(data, str):
                print("响应类型: 字符串，可能是 URI/Base64 订阅")
            else:
                print("响应类型:", type(data).__name__)
        except yaml.YAMLError:
            print("响应不是有效 YAML")
except Exception as e:
    print("请求失败:", type(e).__name__)
