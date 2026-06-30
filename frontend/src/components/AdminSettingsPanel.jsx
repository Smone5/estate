import React, { useEffect, useState, useCallback } from 'react';

const SECTION_LABELS = {
  llm: 'LLM Provider',
  smtp: 'Email (SMTP)',
  storage: 'Storage',
};

const SECTION_ORDER = ['llm', 'smtp', 'storage'];

// Sane default model strings per provider, keyed by the model-purpose this
// panel exposes. Lets switching a provider dropdown auto-fill a model name
// that's actually valid for that provider via LiteLLM, instead of leaving
// behind a stale model string from whichever provider was selected before
// (e.g. Ollama's "llava:latest" surviving a switch to Anthropic).
const PROVIDER_DEFAULT_MODELS = {
  ollama: { fast: 'qwen3:8b', slow: 'qwen3:14b', vision: 'qwen3-vl:8b', embedding: 'nomic-embed-text', pricing: 'qwen3-vl:8b' },
  openai: { fast: 'gpt-5-mini', slow: 'gpt-5', vision: 'gpt-5', embedding: 'text-embedding-3-small', pricing: 'gpt-5' },
  anthropic: { fast: 'claude-haiku-4-5', slow: 'claude-sonnet-4-6', vision: 'claude-sonnet-4-6', embedding: '', pricing: 'claude-sonnet-4-6' },
  google: { fast: 'gemini-2.5-flash', slow: 'gemini-2.5-pro', vision: 'gemini-2.5-pro', embedding: 'text-embedding-004', pricing: 'gemini-2.5-pro' },
  openrouter: { fast: 'anthropic/claude-haiku-4-5', slow: 'anthropic/claude-sonnet-4-6', vision: 'anthropic/claude-sonnet-4-6', embedding: '', pricing: 'anthropic/claude-sonnet-4-6' },
  nvidia: { fast: 'meta/llama-3.3-70b-instruct', slow: 'meta/llama-3.1-405b-instruct', vision: 'meta/llama-3.2-90b-vision-instruct', embedding: '', pricing: 'meta/llama-3.2-90b-vision-instruct' },
};

// Maps each *_PROVIDER setting to the model-purpose key (into
// PROVIDER_DEFAULT_MODELS) and the model setting(s) it should populate.
// Each purpose has its own independent provider so admins can freely mix
// providers (e.g. Ollama for fast, Anthropic for slow, Google for vision).
// LLM_PROVIDER is a legacy fallback for fast/slow — not in this map since
// it doesn't auto-fill models on its own any more.
const PROVIDER_TO_MODEL_FIELDS = {
  FAST_PROVIDER: [{ purpose: 'fast', modelKey: 'FAST_THINKER_MODEL' }],
  SLOW_PROVIDER: [{ purpose: 'slow', modelKey: 'SLOW_THINKER_MODEL' }],
  VISION_PROVIDER: [{ purpose: 'vision', modelKey: 'VISION_MODEL' }],
  EMBEDDING_PROVIDER: [{ purpose: 'embedding', modelKey: 'EMBEDDING_MODEL' }],
  PRICING_PROVIDER: [{ purpose: 'pricing', modelKey: 'PRICING_MODEL' }],
};

// The independent provider slots. Credential fields are shown for every
// unique provider selected across these keys, deduped — so if fast and
// slow both use Anthropic, the API key only appears once.
const PROVIDER_SELECT_KEYS = ['FAST_PROVIDER', 'SLOW_PROVIDER', 'VISION_PROVIDER', 'EMBEDDING_PROVIDER', 'PRICING_PROVIDER'];

// Which credential/connection setting(s) each provider needs. A provider
// used in more than one slot (e.g. NVIDIA for both LLM and Vision) still
// only renders its field(s) once.
const PROVIDER_CREDENTIAL_FIELDS = {
  ollama: ['OLLAMA_BASE_URL'],
  openai: ['OPENAI_API_KEY'],
  anthropic: ['ANTHROPIC_API_KEY'],
  google: ['GEMINI_API_KEY'],
  openrouter: ['OPENROUTER_API_KEY', 'OPENROUTER_BASE_URL'],
  nvidia: ['NVIDIA_API_KEY', 'NVIDIA_BASE_URL'],
};

// Providers where a Base URL is meaningful (self-hosted or non-standard endpoint).
// For all other providers LiteLLM knows the endpoint — only the API key is needed.
const PROVIDERS_WITH_BASE_URL = new Set(['ollama', 'openrouter', 'nvidia']);

// Per-purpose API key + base URL, shown in the credentials section whenever
// that purpose slot has a provider selected. These let each purpose use a
// completely different account or OpenAI-compatible endpoint, fully independent
// of the shared per-company credentials above.
const PURPOSE_CREDENTIAL_FIELDS = {
  FAST_PROVIDER:      ['FAST_API_KEY',      'FAST_BASE_URL'],
  SLOW_PROVIDER:      ['SLOW_API_KEY',      'SLOW_BASE_URL'],
  VISION_PROVIDER:    ['VISION_API_KEY',    'VISION_BASE_URL'],
  EMBEDDING_PROVIDER: ['EMBEDDING_API_KEY', 'EMBEDDING_BASE_URL'],
  PRICING_PROVIDER:   ['PRICING_API_KEY',   'PRICING_BASE_URL'],
};

// Every key listed in PROVIDER_CREDENTIAL_FIELDS or PURPOSE_CREDENTIAL_FIELDS,
// flattened — used to keep these out of the "always visible" field list so they
// only show up via the dynamic credentials section below.
const ALL_CREDENTIAL_KEYS = new Set([
  ...Object.values(PROVIDER_CREDENTIAL_FIELDS).flat(),
  ...Object.values(PURPOSE_CREDENTIAL_FIELDS).flat(),
]);

// Which provider/model setting keys back each "Test Connection" purpose —
// used to assemble the override payload sent to /test-connection so the
// admin can test unsaved draft values, not just whatever's already saved.
const PURPOSE_TO_KEYS = {
  fast: { label: 'Fast LLM', providerKey: 'FAST_PROVIDER', modelKey: 'FAST_THINKER_MODEL' },
  slow: { label: 'Slow LLM', providerKey: 'SLOW_PROVIDER', modelKey: 'SLOW_THINKER_MODEL' },
  vision: { label: 'Vision', providerKey: 'VISION_PROVIDER', modelKey: 'VISION_MODEL' },
  embedding: { label: 'Embedding', providerKey: 'EMBEDDING_PROVIDER', modelKey: 'EMBEDDING_MODEL' },
  pricing: { label: 'Pricing', providerKey: 'PRICING_PROVIDER', modelKey: 'PRICING_MODEL' },
};

function fieldLabel(key) {
  return key
    .toLowerCase()
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

export default function AdminSettingsPanel() {
  const [sections, setSections] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [savingSection, setSavingSection] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);
  // Per-field draft values, keyed by setting key. Only fields the admin has
  // touched are sent on save — secrets left blank mean "leave unchanged".
  const [drafts, setDrafts] = useState({});
  const [touched, setTouched] = useState({});
  const [activeSection, setActiveSection] = useState('llm');
  // Per-purpose ('fast' | 'vision' | 'embedding') Test Connection state:
  // { testing: bool, success: bool|null, detail/error: string, elapsed_ms }
  const [testStatus, setTestStatus] = useState({});

  const SETTING_TABS = [
    { id: 'llm', label: 'LLM Provider' },
    { id: 'smtp', label: 'Email (SMTP)' },
    { id: 'storage', label: 'Storage' },
  ];

  const fetchSettings = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/admin/settings', { credentials: 'same-origin' });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Failed to load settings (${res.status})`);
      }
      const data = await res.json();
      setSections(data);
      setDrafts({});
      setTouched({});
    } catch (err) {
      setError(err.message || 'Failed to load settings');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!sections) {
      fetchSettings();
    }
  }, [sections, fetchSettings]);

  function handleFieldChange(key, value) {
    setDrafts((d) => ({ ...d, [key]: value }));
    setTouched((t) => ({ ...t, [key]: true }));

    // Switching a provider dropdown auto-fills its model field(s) with a
    // sane default for that provider, so the model string doesn't silently
    // stay pointed at the previous provider's naming scheme.
    const modelFields = PROVIDER_TO_MODEL_FIELDS[key];
    if (modelFields && value) {
      const defaults = PROVIDER_DEFAULT_MODELS[value];
      if (defaults) {
        setDrafts((d) => {
          const next = { ...d };
          for (const { purpose, modelKey } of modelFields) {
            const suggestion = defaults[purpose];
            if (suggestion) next[modelKey] = suggestion;
          }
          return next;
        });
        setTouched((t) => {
          const next = { ...t };
          for (const { purpose, modelKey } of modelFields) {
            if (defaults[purpose]) next[modelKey] = true;
          }
          return next;
        });
      }
    }
  }

  async function handleSaveSection(section) {
    setSavingSection(section);
    setError(null);
    setSuccessMessage(null);
    try {
      const updates = {};
      for (const [key, meta] of Object.entries(sections[section])) {
        if (touched[key]) {
          updates[key] = drafts[key] ?? '';
        }
      }
      if (Object.keys(updates).length === 0) {
        setSavingSection(null);
        return;
      }
      const res = await fetch('/api/admin/settings', {
        method: 'PUT',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ updates }),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Failed to save settings (${res.status})`);
      }
      const data = await res.json();
      setSections(data);
      setDrafts((d) => {
        const next = { ...d };
        for (const key of Object.keys(updates)) delete next[key];
        return next;
      });
      setTouched((t) => {
        const next = { ...t };
        for (const key of Object.keys(updates)) delete next[key];
        return next;
      });
      setSuccessMessage(`${SECTION_LABELS[section] || section} settings saved.`);
    } catch (err) {
      setError(err.message || 'Failed to save settings');
    } finally {
      setSavingSection(null);
    }
  }

  // Current effective value of a field: an unsaved draft if the admin has
  // touched it this session, otherwise whatever the server returned.
  function fieldValue(fields, key) {
    if (drafts[key] !== undefined) return drafts[key];
    const meta = fields[key];
    if (!meta) return '';
    return meta.secret ? '' : meta.value ?? '';
  }

  // Credential fields to render for the llm section: the union of whatever
  // PROVIDER_CREDENTIAL_FIELDS lists for each provider currently selected in
  // LLM_PROVIDER / VISION_PROVIDER / EMBEDDING_PROVIDER, deduped so a
  // provider used in two slots only shows its key once.
  function activeCredentialKeys(fields) {
    const seen = new Set();
    const ordered = [];
    for (const providerKey of PROVIDER_SELECT_KEYS) {
      const provider = fieldValue(fields, providerKey);
      // Shared company credentials (e.g. OPENAI_API_KEY) — deduped across slots
      // so if fast and slow both use Anthropic, the key only appears once.
      const credKeys = PROVIDER_CREDENTIAL_FIELDS[provider] || [];
      for (const credKey of credKeys) {
        if (!seen.has(credKey) && fields[credKey]) {
          seen.add(credKey);
          ordered.push(credKey);
        }
      }
      // Per-purpose credentials (FAST_API_KEY, FAST_BASE_URL, etc.) — always shown
      // when a provider is selected for that slot, letting each purpose use its own
      // account or OpenAI-compatible endpoint independently of the shared key above.
      if (provider) {
        for (const credKey of PURPOSE_CREDENTIAL_FIELDS[providerKey] || []) {
          if (!seen.has(credKey) && fields[credKey]) {
            seen.add(credKey);
            ordered.push(credKey);
          }
        }
      }
    }
    return ordered;
  }

  // Fires a minimal real call through the chosen provider/model for one
  // purpose ('fast' | 'vision' | 'embedding'), using current draft values so
  // the admin can verify a combination works before saving it.
  async function handleTestConnection(purpose) {
    const fields = sections.llm;
    const { providerKey, modelKey } = PURPOSE_TO_KEYS[purpose];
    const provider = fieldValue(fields, providerKey);

    const overrides = {};
    if (fields[providerKey]) overrides[providerKey] = provider;
    if (fields[modelKey]) overrides[modelKey] = fieldValue(fields, modelKey);
    for (const credKey of PROVIDER_CREDENTIAL_FIELDS[provider] || []) {
      if (!fields[credKey]) continue;
      // Only send secret fields if the admin has typed a new value this session —
      // otherwise the backend already has the saved value in os.environ and sending
      // an empty string would wipe it out for this test call.
      if (fields[credKey].secret && !drafts[credKey]) continue;
      overrides[credKey] = fieldValue(fields, credKey);
    }
    // Per-purpose key (e.g. FAST_API_KEY) — same rule: skip if secret and not drafted
    const [purposeApiKeyField] = PURPOSE_CREDENTIAL_FIELDS[providerKey] || [];
    if (purposeApiKeyField && fields[purposeApiKeyField]) {
      if (!fields[purposeApiKeyField].secret || drafts[purposeApiKeyField]) {
        overrides[purposeApiKeyField] = fieldValue(fields, purposeApiKeyField);
      }
    }

    setTestStatus((s) => ({ ...s, [purpose]: { testing: true } }));
    try {
      const res = await fetch('/api/admin/settings/test-connection', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ purpose, overrides }),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Test failed (${res.status})`);
      }
      const data = await res.json();
      setTestStatus((s) => ({ ...s, [purpose]: { testing: false, ...data } }));
    } catch (err) {
      setTestStatus((s) => ({
        ...s,
        [purpose]: { testing: false, success: false, error: err.message || 'Test failed' },
      }));
    }
  }

  function renderField(key, meta) {
    const isSecret = meta.secret;
    const currentValue = drafts[key] ?? (isSecret ? '' : meta.value ?? '');

    return (
      <div key={key} style={{ marginBottom: 'var(--space-md)' }}>
        <label className="form-label" htmlFor={`setting-${key}`}>
          {fieldLabel(key)}
        </label>
        {meta.choices ? (
          <select
            id={`setting-${key}`}
            className="form-input"
            value={currentValue}
            onChange={(e) => handleFieldChange(key, e.target.value)}
          >
            <option value="">{isSecret ? '(unchanged)' : '(default)'}</option>
            {meta.choices.map((choice) => (
              <option key={choice} value={choice}>
                {choice}
              </option>
            ))}
          </select>
        ) : (
          <input
            id={`setting-${key}`}
            className="form-input"
            type={isSecret ? 'password' : 'text'}
            value={currentValue}
            onChange={(e) => handleFieldChange(key, e.target.value)}
            placeholder={isSecret ? (meta.is_set ? '•••• configured' : 'Not configured') : ''}
            autoComplete="off"
          />
        )}
      </div>
    );
  }

  return (
    <div className="archival-card" data-testid="admin-settings-panel">
      <div style={{ marginBottom: 'var(--space-md)' }}>
        <h3 style={{ margin: 0, fontFamily: 'var(--font-serif)' }}>Runtime Settings</h3>
        <p className="text-sm text-muted" style={{ margin: '4px 0 0 0' }}>
          LLM provider, email, and storage configuration. Changes apply immediately, no restart required.
        </p>
      </div>

      <div className="admin-tab-nav" style={{ fontSize: '0.875rem', marginBottom: 'var(--space-md)' }}>
        {SETTING_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`btn btn-tab${activeSection === tab.id ? ' active' : ''}`}
            onClick={() => setActiveSection(tab.id)}
            data-testid={`settings-tab-${tab.id}`}
            style={{
              padding: 'var(--space-xs) var(--space-sm)',
              fontSize: '0.85rem',
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div style={{ marginTop: 'var(--space-md)' }}>
        {error && <div className="banner banner-error" style={{ marginBottom: 'var(--space-md)' }}>{error}</div>}
        {successMessage && <div className="banner banner-success" style={{ marginBottom: 'var(--space-md)' }}>{successMessage}</div>}

        {loading && <p className="text-muted">Loading settings…</p>}

        {!loading && sections && (() => {
          const fields = sections[activeSection];
          if (!fields) return null;
          const isLlmSection = activeSection === 'llm';

          if (isLlmSection) {
            // LLM section: one card per purpose with all its fields grouped together.
            // Provider, model, API key, and base URL live in the same card so there's
            // no hunting across separate sections to configure a single model.
            const purposeCards = Object.entries(PURPOSE_TO_KEYS).map(([purpose, { label, providerKey, modelKey }]) => {
              if (!fields[modelKey]) return null;
              const [apiKeyField, baseUrlField] = PURPOSE_CREDENTIAL_FIELDS[providerKey] || [];
              const selectedProvider = fieldValue(fields, providerKey);
              const showBaseUrl = baseUrlField && PROVIDERS_WITH_BASE_URL.has(selectedProvider);
              const status = testStatus[purpose];
              return (
                <div
                  key={purpose}
                  style={{
                    border: '1px solid var(--color-border)',
                    borderRadius: 'var(--radius-md)',
                    padding: 'var(--space-md)',
                    marginBottom: 'var(--space-md)',
                    background: 'var(--color-bg)',
                  }}
                >
                  <h4 style={{ margin: '0 0 var(--space-sm)', fontSize: '0.9rem', fontWeight: 600 }}>{label}</h4>
                  <div className="admin-form-grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
                    {fields[providerKey] && renderField(providerKey, fields[providerKey])}
                    {fields[modelKey] && renderField(modelKey, fields[modelKey])}
                  </div>
                  <div className="admin-form-grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
                    {apiKeyField && fields[apiKeyField] && renderField(apiKeyField, fields[apiKeyField])}
                    {showBaseUrl && fields[baseUrlField] && renderField(baseUrlField, fields[baseUrlField])}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-sm)', marginTop: 'var(--space-xs)' }}>
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={() => handleTestConnection(purpose)}
                      disabled={status?.testing}
                      data-testid={`test-connection-${purpose}`}
                    >
                      {status?.testing ? 'Testing…' : 'Test Connection'}
                    </button>
                    {status && !status.testing && (
                      <span
                        className="text-sm"
                        style={{ color: status.success ? 'var(--color-success, green)' : 'var(--color-error, crimson)' }}
                        data-testid={`test-connection-result-${purpose}`}
                      >
                        {status.success ? `✓ ${status.detail} (${status.elapsed_ms}ms)` : `✗ ${status.error}`}
                      </span>
                    )}
                  </div>
                </div>
              );
            });

            // Shared provider credentials (company-level keys like OPENAI_API_KEY)
            // still shown once at the bottom — they apply as fallback when a purpose
            // doesn't have its own FAST_API_KEY / SLOW_API_KEY etc. set.
            const sharedCredKeys = (() => {
              const seen = new Set(Object.values(PURPOSE_CREDENTIAL_FIELDS).flat());
              const ordered = [];
              for (const providerKey of PROVIDER_SELECT_KEYS) {
                const provider = fieldValue(fields, providerKey);
                for (const credKey of PROVIDER_CREDENTIAL_FIELDS[provider] || []) {
                  if (!seen.has(credKey) && fields[credKey]) {
                    seen.add(credKey);
                    ordered.push(credKey);
                  }
                }
              }
              return ordered;
            })();

            return (
              <div key="llm">
                {purposeCards}
                {sharedCredKeys.length > 0 && (
                  <div
                    style={{
                      border: '1px solid var(--color-border)',
                      borderRadius: 'var(--radius-md)',
                      padding: 'var(--space-md)',
                      marginBottom: 'var(--space-md)',
                      background: 'var(--color-bg)',
                    }}
                  >
                    <h4 style={{ margin: '0 0 var(--space-sm)', fontSize: '0.9rem', fontWeight: 600 }}>
                      Shared Provider Credentials
                    </h4>
                    <p className="text-sm text-muted" style={{ marginBottom: 'var(--space-sm)' }}>
                      Used as fallback when a purpose above has no per-model API key set.
                    </p>
                    {sharedCredKeys.map((key) => renderField(key, fields[key]))}
                  </div>
                )}
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={() => handleSaveSection(activeSection)}
                  disabled={savingSection === activeSection}
                  data-testid={`save-settings-${activeSection}`}
                >
                  {savingSection === activeSection ? 'Saving…' : 'Save LLM Settings'}
                </button>
              </div>
            );
          }

          // Non-LLM sections (smtp, storage) keep the original flat layout.
          return (
            <div key={activeSection}>
              {Object.keys(fields).map((key) => renderField(key, fields[key]))}
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={() => handleSaveSection(activeSection)}
                disabled={savingSection === activeSection}
                style={{ marginTop: 'var(--space-xs)' }}
                data-testid={`save-settings-${activeSection}`}
              >
                {savingSection === activeSection ? 'Saving…' : `Save ${SECTION_LABELS[activeSection] || activeSection}`}
              </button>
            </div>
          );
        })()}
      </div>
    </div>
  );
}
