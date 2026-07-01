import React, { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useMediationStore } from '../store/useMediationStore';
import {
  cloneSimulationConfig,
  DEFAULT_SIMULATION_CONFIG,
  loadSessionSimulationContext,
  SIMULATION_IMAGE_OPTIONS,
} from '../utils/simulationConfig';

function participantTotal(config, participant) {
  return config.items
    .filter((item) => item.enabled)
    .reduce((sum, item) => sum + Number(item.companion_points?.[participant] || 0), 0);
}

export default function AdminSimulationManager({ sessionId }) {
  const loadSessionDetails = useMediationStore((state) => state.loadSessionDetails);
  const [config, setConfig] = useState(() => cloneSimulationConfig());
  const [practiceStatus, setPracticeStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState(null);

  useEffect(() => {
    if (!sessionId) {
      setLoading(false);
      return;
    }
    loadSessionSimulationContext(sessionId)
      .then((context) => setConfig(context.config))
      .then(() => fetch(`/api/sessions/${sessionId}/simulation/status`, { credentials: 'same-origin' }))
      .then((response) => (response.ok ? response.json() : null))
      .then(setPracticeStatus)
      .catch((error) => setMessage({ type: 'error', text: error.message }))
      .finally(() => setLoading(false));
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) return undefined;
    const interval = window.setInterval(() => {
      fetch(`/api/sessions/${sessionId}/simulation/status`, { credentials: 'same-origin' })
        .then((response) => (response.ok ? response.json() : null))
        .then((status) => { if (status) setPracticeStatus(status); })
        .catch(() => {});
    }, 5000);
    return () => window.clearInterval(interval);
  }, [sessionId]);

  const refreshStatus = async () => {
    const response = await fetch(`/api/sessions/${sessionId}/simulation/status`, {
      credentials: 'same-origin',
    });
    if (response.ok) setPracticeStatus(await response.json());
  };

  const enabledCount = config.items.filter((item) => item.enabled).length;
  const jordanTotal = useMemo(() => participantTotal(config, 'jordan'), [config]);
  const caseyTotal = useMemo(() => participantTotal(config, 'casey'), [config]);
  const isValid = enabledCount >= 5 && enabledCount <= 10 && jordanTotal === 1000 && caseyTotal === 1000;

  const updateTopLevel = (field, value) => {
    setConfig((current) => ({ ...current, [field]: value }));
    setMessage(null);
  };

  const updateItem = (itemId, field, value) => {
    setConfig((current) => ({
      ...current,
      items: current.items.map((item) =>
        item.id === itemId ? { ...item, [field]: value } : item,
      ),
    }));
    setMessage(null);
  };

  const updateCompanion = (itemId, participant, value) => {
    setConfig((current) => ({
      ...current,
      items: current.items.map((item) =>
        item.id === itemId
          ? {
              ...item,
              companion_points: {
                ...item.companion_points,
                [participant]: Math.max(0, Number(value) || 0),
              },
            }
          : item,
      ),
    }));
    setMessage(null);
  };

  const balanceParticipant = (participant) => {
    setConfig((current) => {
      const enabled = current.items.filter((item) => item.enabled);
      if (!enabled.length) return current;
      const total = participantTotal(current, participant);
      const balanced = {};
      if (total === 0) {
        enabled.forEach((item, index) => { balanced[item.id] = index === 0 ? 1000 : 0; });
      } else {
        let used = 0;
        enabled.forEach((item) => {
          balanced[item.id] = Math.floor(
            (Number(item.companion_points?.[participant] || 0) / total) * 1000,
          );
          used += balanced[item.id];
        });
        balanced[enabled[0].id] += 1000 - used;
      }
      return {
        ...current,
        items: current.items.map((item) =>
          item.enabled
            ? {
                ...item,
                companion_points: {
                  ...item.companion_points,
                  [participant]: balanced[item.id],
                },
              }
            : item,
        ),
      };
    });
  };

  const save = async () => {
    if (!isValid) return;
    setSaving(true);
    setMessage(null);
    try {
      const response = await fetch(`/api/sessions/${sessionId}/simulation/config`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Could not save the practice estate.');
      setConfig(data.config);
      await refreshStatus();
      await loadSessionDetails?.();
      setMessage({
        type: 'success',
        text: 'Practice estate published. Registered-heir completion was reset so everyone practices this exact version.',
      });
    } catch (error) {
      setMessage({ type: 'error', text: error.message });
    } finally {
      setSaving(false);
    }
  };

  const reset = async () => {
    setSaving(true);
    setMessage(null);
    try {
      const response = await fetch(`/api/sessions/${sessionId}/simulation/reset`, { method: 'POST' });
      const data = response.ok ? await response.json() : { config: cloneSimulationConfig(DEFAULT_SIMULATION_CONFIG) };
      setConfig(data.config);
      await refreshStatus();
      await loadSessionDetails?.();
      setMessage({ type: 'success', text: 'The original fictional practice estate has been restored.' });
    } catch {
      setConfig(cloneSimulationConfig(DEFAULT_SIMULATION_CONFIG));
      setMessage({ type: 'error', text: 'Defaults were restored locally, but the server could not be reached.' });
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="archival-card"><p className="text-muted">Loading practice estate…</p></div>;
  }

  if (!sessionId) {
    return <div className="archival-card"><p className="text-muted">Open a mediation session to configure its practice allocation.</p></div>;
  }

  return (
    <section className="simulation-manager">
      <header className="simulation-manager-header">
        <div>
          <div className="practice-kicker">Executor-managed rehearsal</div>
          <h2>Allocation Simulation Manager</h2>
          <p>Publish the fictional rehearsal for this session, monitor registered-heir completion, then launch the real allocation.</p>
        </div>
        <div>
          <Link className="btn btn-secondary" to={`/admin/practice-preview/${sessionId}`} target="_blank" rel="noreferrer">
            Preview simulation
          </Link>
          <button type="button" className="btn btn-primary" onClick={save} disabled={!isValid || saving}>
            {saving ? 'Publishing…' : 'Publish changes'}
          </button>
        </div>
      </header>

      {message && (
        <div className={`banner ${message.type === 'success' ? 'banner-info' : 'banner-error'}`} role="status">
          {message.text}
        </div>
      )}

      <div className="simulation-manager-summary">
        <div><strong>{enabledCount}</strong><span>enabled items</span><small>Required: 5–10</small></div>
        <div className={jordanTotal === 1000 ? 'is-valid' : 'is-invalid'}>
          <strong>{jordanTotal}</strong><span>Jordan’s points</span>
          {jordanTotal !== 1000 && <button type="button" onClick={() => balanceParticipant('jordan')}>Balance to 1,000</button>}
        </div>
        <div className={caseyTotal === 1000 ? 'is-valid' : 'is-invalid'}>
          <strong>{caseyTotal}</strong><span>Casey’s points</span>
          {caseyTotal !== 1000 && <button type="button" onClick={() => balanceParticipant('casey')}>Balance to 1,000</button>}
        </div>
      </div>

      <section className="simulation-manager-flow">
        <div>
          <span>1</span>
          <strong>Publish practice</strong>
          <small>{practiceStatus?.published ? 'Published for this session' : 'Not published yet'}</small>
        </div>
        <div>
          <span>2</span>
          <strong>Heirs rehearse</strong>
          <small>{practiceStatus?.completed_heirs || 0} of {practiceStatus?.total_heirs || 0} complete</small>
        </div>
        <div>
          <span>3</span>
          <strong>Launch real allocation</strong>
          <small>
            {config.required_for_launch
              ? 'Unlocks after every registered heir completes'
              : 'Practice is recommended, not required'}
          </small>
        </div>
      </section>

      <div className="simulation-manager-requirement">
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={config.required_for_launch !== false}
            onChange={(event) => updateTopLevel('required_for_launch', event.target.checked)}
          />
          <span>
            <strong>Require every registered heir to finish practice before launch</strong>
            <small>Turn this off only when an accessibility or timing exception makes practice impractical.</small>
          </span>
        </label>
      </div>

      {practiceStatus?.heirs?.length > 0 && (
        <div className="simulation-manager-heirs">
          <h3>Registered heir practice status</h3>
          {practiceStatus.heirs.map((heir) => (
            <div key={heir.heir_id}>
              <span>{heir.display_name}</span>
              <small>{heir.status}</small>
              <strong className={heir.practice_completed_at ? 'is-complete' : ''}>
                {heir.practice_completed_at ? 'Practice complete' : 'Not completed'}
              </strong>
            </div>
          ))}
        </div>
      )}

      <div className="simulation-manager-basics">
        <label>
          <span>Practice estate title</span>
          <input className="form-input" value={config.title} onChange={(event) => updateTopLevel('title', event.target.value)} />
        </label>
        <label>
          <span>Welcome message</span>
          <textarea className="form-input form-textarea" value={config.welcome_message} onChange={(event) => updateTopLevel('welcome_message', event.target.value)} />
        </label>
      </div>

      <div className="simulation-manager-items">
        {config.items.map((item, index) => (
          <article key={item.id} className={!item.enabled ? 'is-disabled' : ''}>
            <div className="simulation-manager-item-image">
              <img src={item.image} alt="" />
              <label>
                <input
                  type="checkbox"
                  checked={item.enabled}
                  disabled={item.enabled && enabledCount <= 5}
                  onChange={(event) => updateItem(item.id, 'enabled', event.target.checked)}
                />
                Included in rehearsal
              </label>
            </div>
            <div className="simulation-manager-item-form">
              <div className="simulation-manager-item-number">Item {index + 1}</div>
              <div className="simulation-manager-two-col">
                <label><span>Title</span><input className="form-input" value={item.title} onChange={(event) => updateItem(item.id, 'title', event.target.value)} /></label>
                <label><span>Category</span><input className="form-input" value={item.category} onChange={(event) => updateItem(item.id, 'category', event.target.value)} /></label>
              </div>
              <label><span>Description</span><textarea className="form-input" value={item.description} onChange={(event) => updateItem(item.id, 'description', event.target.value)} /></label>
              <label><span>Fictional family story</span><textarea className="form-input" value={item.story} onChange={(event) => updateItem(item.id, 'story', event.target.value)} /></label>
              <div className="simulation-manager-two-col">
                <label><span>Estimated value range</span><input className="form-input" value={item.value_range} onChange={(event) => updateItem(item.id, 'value_range', event.target.value)} /></label>
                <label>
                  <span>Catalog photograph</span>
                  <select className="form-input" value={item.image} onChange={(event) => updateItem(item.id, 'image', event.target.value)}>
                    {SIMULATION_IMAGE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                  </select>
                </label>
              </div>
              <div className="simulation-manager-points">
                <span>Fictional private point sheets</span>
                <label>Jordan <input type="number" min="0" max="1000" step="10" value={item.companion_points.jordan} onChange={(event) => updateCompanion(item.id, 'jordan', event.target.value)} /></label>
                <label>Casey <input type="number" min="0" max="1000" step="10" value={item.companion_points.casey} onChange={(event) => updateCompanion(item.id, 'casey', event.target.value)} /></label>
              </div>
            </div>
          </article>
        ))}
      </div>

      <footer className="simulation-manager-footer">
        <div>
          <strong>Publishing a changed rehearsal resets completion.</strong>
          <span>This ensures the launch gate refers to the same version every registered heir experienced.</span>
        </div>
        <button type="button" className="btn btn-secondary" onClick={reset} disabled={saving}>Restore original simulation</button>
        <button type="button" className="btn btn-primary" onClick={save} disabled={!isValid || saving}>Publish changes</button>
      </footer>
    </section>
  );
}
