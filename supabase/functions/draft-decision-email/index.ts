// draft-decision-email — turns a tracker-shorthand ai_decisions row into a
// clear, professional email a non-technical recipient can act on, using Claude.
//
// Security: the caller's JWT is forwarded, so the read of ai_decisions runs
// under their RLS — reads are admin-only, so non-admins get no row and are
// rejected. The Anthropic key lives in the function's secrets, never the client.
//
// Deploy:   supabase functions deploy draft-decision-email
// Secret:   ANTHROPIC_API_KEY (already set for ask-portfolio; secrets are project-wide)

import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';

const cors = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
};

function json(obj: unknown, status = 200) {
  return new Response(JSON.stringify(obj), { status, headers: { ...cors, 'content-type': 'application/json' } });
}

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: cors });
  try {
    const { decision_id, greeting_names, sender_name } = await req.json();
    if (!decision_id || typeof decision_id !== 'string') return json({ error: 'Missing decision_id.' }, 400);

    const supabase = createClient(
      Deno.env.get('SUPABASE_URL')!,
      Deno.env.get('SUPABASE_ANON_KEY')!,
      { global: { headers: { Authorization: req.headers.get('Authorization') ?? '' } } },
    );

    // RLS restricts ai_decisions reads to admins — this both fetches and authorizes.
    const { data: d, error } = await supabase
      .from('ai_decisions')
      .select('decision_needed, who_decides, urgency, notes_context, related_project_text, related_project_id')
      .eq('id', decision_id)
      .maybeSingle();
    if (error) return json({ error: error.message }, 400);
    if (!d) return json({ error: 'Not authorized, or decision not found.' }, 403);

    let projectName = d.related_project_text || '';
    if (!projectName && d.related_project_id) {
      const { data: p } = await supabase.from('ai_projects').select('project_name').eq('id', d.related_project_id).maybeSingle();
      projectName = p?.project_name || '';
    }

    const apiKey = Deno.env.get('ANTHROPIC_API_KEY');
    if (!apiKey) {
      console.error('draft-decision-email: ANTHROPIC_API_KEY secret is not set on this project');
      return json({ error: 'ANTHROPIC_API_KEY is not set on the function.' }, 500);
    }

    const recipients = Array.isArray(greeting_names) && greeting_names.length
      ? greeting_names.join(', ')
      : (d.who_decides || 'the decision owners');

    const prompt = `You are writing an internal email for THMedia (a home-improvement magazine publisher). The sender runs the company's AI-projects tracker; the recipients are busy managers who do NOT live in that tracker and won't understand its shorthand.

Write an email asking the recipients to make a decision. The tracker entry below is written in internal shorthand — your job is to unpack it into plain English: explain what is actually being decided, why it matters, and exactly what you need from them. Expand abbreviations, drop jargon, and don't assume they remember the project.

TRACKER ENTRY
Decision needed: ${d.decision_needed}
${projectName ? `Related project: ${projectName}` : 'Related project: (none — general/governance item)'}
Context notes: ${d.notes_context || '(none)'}
Urgency: ${d.urgency || 'Soon'} (Blocking = work is stopped until decided; Next Up = needed within a week or so; Soon = within a few weeks; Eventually = no deadline)

RECIPIENTS: ${recipients}
SENDER: ${sender_name || 'the AI projects team'}
DASHBOARD LINK (include near the end): https://anguslindsay-a11y.github.io/thm-ai-projects-dashboard/?v=decisions

REQUIREMENTS
- Greeting: "Hi ${recipients}," then the body.
- Professional but warm and conversational — a colleague asking for help, not a system notification.
- Plain text only: no markdown, no bullets unless genuinely clearer, no headings.
- 120–180 words. One clear ask. End by inviting them to reply or grab the sender to talk it through, then "Thanks," and the sender's first name.
- Phrase the urgency as a natural sentence, never as a label.
- The subject should say what's being decided in plain words, max ~70 characters.`;

    const resp = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-api-key': apiKey, 'anthropic-version': '2023-06-01' },
      body: JSON.stringify({
        model: 'claude-opus-4-8',
        max_tokens: 1000,
        output_config: {
          format: {
            type: 'json_schema',
            schema: {
              type: 'object',
              properties: { subject: { type: 'string' }, body: { type: 'string' } },
              required: ['subject', 'body'],
              additionalProperties: false,
            },
          },
        },
        messages: [{ role: 'user', content: prompt }],
      }),
    });
    if (!resp.ok) {
      console.error('draft-decision-email: Anthropic API error', resp.status, await resp.text());
      return json({ error: `Anthropic API error ${resp.status}` }, 502);
    }
    const out = await resp.json();
    const text = out?.content?.find((b: { type: string }) => b.type === 'text')?.text;
    if (!text) return json({ error: 'No draft returned.' }, 502);
    const draft = JSON.parse(text);
    return json({ subject: draft.subject, body: draft.body });
  } catch (e) {
    console.error('draft-decision-email: unhandled error', e);
    return json({ error: String(e) }, 500);
  }
});
