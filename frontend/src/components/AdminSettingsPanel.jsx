import React, { useEffect, useState, useCallback } from 'react';

const SECTION_LABELS = {
  llm: 'LLM Provider',
  smtp: 'Email (SMTP)',
  storage: 'Storage',
};

const SECTION_ORDER = ['llm', 'smtp', 'storage'];

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
  const [isOpen, setIsOpen] = useState(false);

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
    if (isOpen && !sections) {
      fetchSettings();
    }
  }, [isOpen, sections, fetchSettings]);

  function handleFieldChange(key, value) {
    setDrafts((d) => ({ ...d, [key]: value }));
    setTouched((t) => ({ ...t, [key]: true }));
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
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          cursor: 'pointer',
        }}
        onClick={() => setIsOpen((o) => !o)}
        role="button"
        tabIndex={0}
        aria-expanded={isOpen}
      >
        <div>
          <h3 style={{ margin: 0 }}>Runtime Settings</h3>
          <p className="text-sm text-muted" style={{ margin: 0 }}>
            LLM provider, email, and storage configuration. Changes apply immediately, no restart required.
          </p>
        </div>
        <span aria-hidden="true">{isOpen ? '▲' : '▼'}</span>
      </div>

      {isOpen && (
        <div style={{ marginTop: 'var(--space-lg)' }}>
          {error && <div className="banner banner-error">{error}</div>}
          {successMessage && <div className="banner banner-success">{successMessage}</div>}

          {loading && <p className="text-muted">Loading settings…</p>}

          {!loading && sections && SECTION_ORDER.map((section) => {
            const fields = sections[section];
            if (!fields) return null;
            return (
              <div key={section} style={{ marginBottom: 'var(--space-xl)' }}>
                <h4 style={{ marginBottom: 'var(--space-sm)' }}>{SECTION_LABELS[section] || section}</h4>
                {Object.entries(fields).map(([key, meta]) => renderField(key, meta))}
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={() => handleSaveSection(section)}
                  disabled={savingSection === section}
                >
                  {savingSection === section ? 'Saving…' : `Save ${SECTION_LABELS[section] || section}`}
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
