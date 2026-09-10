// Cloudflare Worker: serves site/ as static assets and answers /api/live from the Twitch Helix API
// so the masthead can show a LIVE pill while PokeBenchTV is streaming.
// Secrets (wrangler secret put): TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET. Unset = always {live:false}.
const CHANNEL = 'pokebenchtv';
const CACHE_MS = 60000;
let token = {value: null, expires: 0};
let cached = {body: null, expires: 0};

async function appToken(env) {
  if (token.value && Date.now() < token.expires) return token.value;
  const response = await fetch('https://id.twitch.tv/oauth2/token', {
    method: 'POST',
    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
    body: new URLSearchParams({client_id: env.TWITCH_CLIENT_ID, client_secret: env.TWITCH_CLIENT_SECRET, grant_type: 'client_credentials'}),
  });
  if (!response.ok) throw new Error(`twitch token ${response.status}`);
  const data = await response.json();
  token = {value: data.access_token, expires: Date.now() + Math.max(60, data.expires_in - 300) * 1000};
  return token.value;
}

async function liveStatus(env) {
  if (cached.body && Date.now() < cached.expires) return cached.body;
  const body = {live: false, channel: CHANNEL, url: `https://www.twitch.tv/${CHANNEL}`};
  if (!env.TWITCH_CLIENT_ID || !env.TWITCH_CLIENT_SECRET) return {...body, configured: false};
  const response = await fetch(`https://api.twitch.tv/helix/streams?user_login=${CHANNEL}`, {
    headers: {'Client-Id': env.TWITCH_CLIENT_ID, Authorization: `Bearer ${await appToken(env)}`},
  });
  if (response.status === 401) token = {value: null, expires: 0};  // revoked or expired: the next poll re-mints
  if (!response.ok) throw new Error(`twitch helix ${response.status}`);
  const stream = (await response.json()).data?.[0];
  if (stream) Object.assign(body, {live: true, title: stream.title, viewers: stream.viewer_count, started_at: stream.started_at});
  cached = {body, expires: Date.now() + CACHE_MS};
  return body;
}

export default {
  async fetch(request, env) {
    if (new URL(request.url).pathname === '/api/live') {
      try {
        return Response.json(await liveStatus(env), {headers: {'Cache-Control': 'public, max-age=30'}});
      } catch (error) {
        return Response.json({live: false, error: String(error)}, {status: 502, headers: {'Cache-Control': 'no-store'}});
      }
    }
    return env.ASSETS.fetch(request);
  },
};
