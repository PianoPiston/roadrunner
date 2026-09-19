import express from 'express';
import { spawn } from 'child_process';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ACME_AGENT_DIR = path.resolve(__dirname, '..');
const TIMEOUT_MS = 5 * 60 * 1000;

const app = express();
app.use(express.json());

app.post('/api/ask', (req, res) => {
  const message = typeof req.body?.message === 'string' ? req.body.message.trim() : '';
  if (!message) {
    res.status(400).json({ error: 'Message must not be empty.' });
    return;
  }

  const child = spawn('poetry', ['run', 'acme-agent', 'ask', message], {
    cwd: ACME_AGENT_DIR,
  });

  let stdout = '';
  let stderr = '';
  let settled = false;

  const timer = setTimeout(() => {
    settled = true;
    child.kill('SIGKILL');
    res.status(504).json({ error: 'acme-agent timed out.' });
  }, TIMEOUT_MS);

  child.stdout.on('data', (chunk) => {
    stdout += chunk.toString();
  });
  child.stderr.on('data', (chunk) => {
    stderr += chunk.toString();
  });

  child.on('error', (err) => {
    if (settled) return;
    settled = true;
    clearTimeout(timer);
    res.status(500).json({ error: `Failed to run acme-agent: ${err.message}` });
  });

  child.on('close', (code) => {
    if (settled) return;
    settled = true;
    clearTimeout(timer);
    if (code === 0 || code === 2) {
      res.json({ output: stdout.trim() });
    } else {
      res.status(500).json({ error: (stderr || stdout || `acme-agent exited with code ${code}`).trim() });
    }
  });
});

const PORT = process.env.PORT || 3001;
app.listen(PORT, () => {
  console.log(`acme-agent API server listening on http://localhost:${PORT}`);
});
