// Vercel serverless function. Keeps the Anthropic API key server-side —
// never sent to or readable by the browser. Configure ANTHROPIC_API_KEY
// in the Vercel project's Environment Variables.
module.exports = async (req, res) => {
  if (req.method !== "POST") {
    res.status(405).json({ error: "Method not allowed" });
    return;
  }

  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    res.status(500).json({ error: "Chat isn't configured yet — ANTHROPIC_API_KEY is missing on the server." });
    return;
  }

  let body = req.body;
  if (typeof body === "string") {
    try { body = JSON.parse(body); } catch (e) { body = {}; }
  }
  body = body || {};

  const message = String(body.message || "").trim().slice(0, 2000);
  const context = String(body.context || "").slice(0, 8000);
  const historyIn = Array.isArray(body.history) ? body.history : [];

  if (!message) {
    res.status(400).json({ error: "Message is required." });
    return;
  }

  const history = historyIn
    .filter(function (m) { return m && (m.role === "user" || m.role === "assistant") && typeof m.content === "string"; })
    .slice(-10)
    .map(function (m) { return { role: m.role, content: m.content.slice(0, 2000) }; });

  const system =
    "You are a concise assistant embedded in Disastorous, a tool that scores disaster/crime risk near a " +
    "place using recent news and live hazard feeds. Answer the user's question using ONLY the context " +
    "below (the news articles and hazard events pulled up by their current search). If the context doesn't " +
    "contain the answer, say so plainly rather than guessing or using outside knowledge as if it were from " +
    "the search. Keep answers under 150 words. Never present anything here as an official emergency " +
    "service, compliance determination, or professional safety advice — this is automated news analysis.\n\n" +
    "CONTEXT FROM THE CURRENT SEARCH:\n" + (context || "(no search has been run yet on this page)");

  try {
    const resp = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "x-api-key": apiKey,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
      },
      body: JSON.stringify({
        model: "claude-sonnet-5",
        max_tokens: 400,
        system: system,
        messages: history.concat([{ role: "user", content: message }])
      })
    });
    const data = await resp.json();
    if (!resp.ok) {
      const msg = (data && data.error && data.error.message) || ("Anthropic API returned " + resp.status);
      res.status(resp.status).json({ error: msg });
      return;
    }
    const reply = (data.content && data.content[0] && data.content[0].text) || "(no reply)";
    res.status(200).json({ reply: reply });
  } catch (err) {
    res.status(500).json({ error: "Couldn't reach the chat service — try again in a moment." });
  }
};
