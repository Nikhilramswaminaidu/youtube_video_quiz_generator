/**
 * Cloudflare Worker: YouTube Transcript Proxy
 *
 * Proxies YouTube's timedtext API through Cloudflare's edge network,
 * bypassing YouTube's IP blocking of cloud/datacenter IPs.
 *
 * Free tier: 100,000 requests/day — more than enough for this app.
 *
 * SETUP:
 * 1. Create a free Cloudflare account at https://dash.cloudflare.com/sign-up
 * 2. Go to Workers & Pages → Create Application → Create Worker
 * 3. Paste this entire file as the worker code
 * 4. Deploy — you'll get a URL like https://youtube-transcript-proxy.YOUR-NAME.workers.dev
 * 5. Set the YOUTUBE_PROXY_URL env var on your Render deployment to that URL
 *
 * Example:
 *   YOUTUBE_PROXY_URL=https://youtube-transcript-proxy.myname.workers.dev
 */

export default {
  async fetch(request) {
    // Handle CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type",
        },
      });
    }

    const url = new URL(request.url);
    const videoId = url.searchParams.get("v");
    const lang = url.searchParams.get("lang") || "en";
    const fmt = url.searchParams.get("fmt") || "srv1";

    if (!videoId) {
      return new Response(
        JSON.stringify({
          error: "Missing video ID. Use ?v=VIDEO_ID&lang=en&fmt=srv1",
        }),
        {
          status: 400,
          headers: {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
          },
        }
      );
    }

    // Proxy YouTube's timedtext API
    const ytUrl = `https://www.youtube.com/api/timedtext?v=${encodeURIComponent(videoId)}&lang=${encodeURIComponent(lang)}&fmt=${encodeURIComponent(fmt)}`;

    try {
      const response = await fetch(ytUrl, {
        headers: {
          "User-Agent":
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        },
      });

      const text = await response.text();

      return new Response(text, {
        status: response.status,
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Content-Type":
            response.headers.get("Content-Type") || "text/xml; charset=utf-8",
        },
      });
    } catch (error) {
      return new Response(
        JSON.stringify({ error: error.message }),
        {
          status: 502,
          headers: {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
          },
        }
      );
    }
  },
};