// ask-portfolio — answers natural-language questions about the AI projects
// portfolio using Claude, grounded ONLY in the live ai_projects data.
//
// Security: the caller's JWT is forwarded, so the read of ai_projects runs
// under their RLS — only admins can read it. Non-admins get no rows and are
// rejected. The Anthropic key lives in the function's secrets, never the client.
//
// Deploy:   supabase functions deploy ask-portfolio
// Secret:   supabase secrets set ANTHROPIC_API_KEY=sk-ant-...
//           (SUPABASE_URL / SUPABASE_ANON_KEY are provided automatically)

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
    const { question } = await req.json();
    if (!question || typeof question !== 'string') return json({ error: 'Missing question.' }, 400);

    const supabase = createClient(
      Deno.env.get('SUPABASE_URL')!,
      Deno.env.get('SUPABASE_ANON_KEY')!,
      { global: { headers: { Authorization: req.headers.get('Authorization') ?? '' } } },
    );

    // RLS restricts ai_projects reads to admins — so this both fetches data and authorizes.
    const { data: projects, error } = await supabase
      .from('ai_projects')
      .select('project_name, theme, status, owners, progress, target_date, impact, ease, strategic_fit, score, priority, success_metric, risk_flags, description, notes');
    if (error) return json({ error: error.message }, 400);
    if (!projects || projects.length === 0) return json({ error: 'Not authorized, or no projects to analyze.' }, 403);

    const apiKey = Deno.env.get('ANTHROPIC_API_KEY');
    if (!apiKey) return json({ error: 'ANTHROPIC_API_KEY is not set on the function.' }, 500);

    const context = projects.map((p: Record<string, unknown>) => {
      const owners = Array.isArray(p.owners) ? (p.owners as string[]).join('/') : '';
      const risks = Array.isArray(p.risk_flags) ? (p.risk_flags as string[]).join(',') : '';
      const pct = Math.round((Number(p.progress) || 0) * 100);
      return `- ${p.project_name} [${p.theme}] status=${p.status} progress=${pct}% target=${p.target_date || 'TBD'} score=${p.score}/15 priority=${p.priority || '-'} owners=${owners || '-'} risks=${risks || '-'}${p.success_metric ? ` metric="${p.success_metric}"` : ''}`;
    }).join('\n');

    const prompt = `You are an analyst for THMedia's AI Projects portfolio. Answer the question using ONLY the project data below. Be concise and specific, reference projects by name, and use short bullet points where helpful. If the data cannot answer the question, say so plainly.\n\nPROJECTS:\n${context}\n\nQUESTION: ${question}`;

    const resp = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-api-key': apiKey, 'anthropic-version': '2023-06-01' },
      body: JSON.stringify({
        model: 'claude-sonnet-4-6',
        max_tokens: 900,
        messages: [{ role: 'user', content: prompt }],
      }),
    });
    if (!resp.ok) return json({ error: `Anthropic API error ${resp.status}` }, 502);
    const out = await resp.json();
    const answer = out?.content?.[0]?.text ?? 'No answer returned.';
    return json({ answer });
  } catch (e) {
    return json({ error: String(e) }, 500);
  }
});
