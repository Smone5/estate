import React, { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  cloneSimulationConfig,
  DEFAULT_SIMULATION_CONFIG,
  loadHeirSimulationContext,
  loadSessionSimulationContext,
} from '../utils/simulationConfig';

const PARTICIPANTS = [
  { id: 'you', name: 'You', note: 'Practice participant' },
  { id: 'jordan', name: 'Jordan', note: 'Fictional heir' },
  { id: 'casey', name: 'Casey', note: 'Fictional heir' },
];

const STEPS = [
  { id: 'welcome', label: 'Welcome' },
  { id: 'catalog', label: 'Explore items' },
  { id: 'allocate', label: 'Allocate points' },
  { id: 'review', label: 'Review & submit' },
  { id: 'waiting', label: 'Waiting room' },
  { id: 'result', label: 'Result' },
];

function emptyPoints(items) {
  return Object.fromEntries(items.map((item) => [item.id, 0]));
}

function sumPoints(points) {
  return Object.values(points).reduce((sum, value) => sum + Number(value || 0), 0);
}

function assignmentKey(items, assignment) {
  return items.map((item) => PARTICIPANTS.findIndex((p) => p.id === assignment[item.id])).join('');
}

export function simulateFullAllocation(items, valuations) {
  const activeItems = items.filter((item) => item.enabled !== false);
  const assignmentsToCheck = PARTICIPANTS.length ** activeItems.length;
  let best = null;

  const visit = (index, assignment, utility) => {
    if (index === activeItems.length) {
      const product = PARTICIPANTS.reduce(
        (total, participant) => total * utility[participant.id],
        1,
      );
      const candidate = {
        assignment: { ...assignment },
        utility: { ...utility },
        product,
      };
      if (
        !best ||
        candidate.product > best.product ||
        (candidate.product === best.product &&
          assignmentKey(activeItems, candidate.assignment) <
            assignmentKey(activeItems, best.assignment))
      ) {
        best = candidate;
      }
      return;
    }

    const item = activeItems[index];
    PARTICIPANTS.forEach((participant) => {
      assignment[item.id] = participant.id;
      utility[participant.id] += valuations[participant.id][item.id] || 0;
      visit(index + 1, assignment, utility);
      utility[participant.id] -= valuations[participant.id][item.id] || 0;
    });
  };

  visit(
    0,
    {},
    Object.fromEntries(PARTICIPANTS.map((participant) => [participant.id, 0])),
  );

  const tieEvents = activeItems
    .map((item) => {
      const bids = PARTICIPANTS.map((participant) => ({
        id: participant.id,
        points: valuations[participant.id][item.id] || 0,
      }));
      const high = Math.max(...bids.map((bid) => bid.points));
      const tied = bids.filter((bid) => bid.points === high && high > 0);
      return tied.length > 1
        ? {
            item,
            tied: tied.map((bid) => bid.id),
            winner: best.assignment[item.id],
            points: high,
          }
        : null;
    })
    .filter(Boolean);

  return { ...best, assignmentsToCheck, tieEvents };
}

function PracticeHeader({ step, onRestart, restartArmed, registered }) {
  return (
    <div className="rehearsal-topbar">
      <Link to={registered ? '/dashboard' : '/login'} className="rehearsal-exit">← Leave practice</Link>
      <div className="rehearsal-mode">
        <span aria-hidden="true" />
        Simulation — no real estate data
      </div>
      <button type="button" onClick={onRestart} className={restartArmed ? 'is-armed' : ''}>
        {restartArmed ? 'Confirm restart' : 'Restart simulation'}
      </button>
      <span className="sr-only">Current step: {step}</span>
    </div>
  );
}

function StepRail({ currentStep, maxStep, onStep }) {
  const currentIndex = STEPS.findIndex((step) => step.id === currentStep);
  return (
    <nav className="rehearsal-step-rail" aria-label="Simulation progress">
      {STEPS.map((step, index) => (
        <button
          key={step.id}
          type="button"
          className={`${index === currentIndex ? 'is-current' : ''}${index < currentIndex ? ' is-complete' : ''}`}
          disabled={index > maxStep}
          onClick={() => onStep(step.id)}
          aria-current={index === currentIndex ? 'step' : undefined}
        >
          <span>{index < currentIndex ? '✓' : index + 1}</span>
          {step.label}
        </button>
      ))}
    </nav>
  );
}

function ItemDetail({ item, points, onClose, onAllocate }) {
  if (!item) return null;
  return (
    <div className="rehearsal-modal-backdrop" role="presentation" onClick={onClose}>
      <article
        className="rehearsal-item-detail"
        role="dialog"
        aria-modal="true"
        aria-labelledby="practice-item-title"
        onClick={(event) => event.stopPropagation()}
      >
        <img src={item.image} alt={item.title} />
        <div>
          <button type="button" className="close-btn" onClick={onClose} aria-label="Close item details">×</button>
          <span className="practice-kicker">{item.category}</span>
          <h2 id="practice-item-title">{item.title}</h2>
          <p>{item.description}</p>
          <blockquote>“{item.story}”</blockquote>
          <dl>
            <div><dt>Estimated value</dt><dd>{item.value_range || 'Not listed'}</dd></div>
            <div><dt>Your practice points</dt><dd>{points || 0} / 1,000</dd></div>
          </dl>
          <button type="button" className="btn btn-primary" onClick={() => onAllocate(item.id)}>
            Allocate points to this item
          </button>
        </div>
      </article>
    </div>
  );
}

function AlgorithmExplainer() {
  return (
    <section className="rehearsal-algorithm" aria-labelledby="practice-algorithm-title">
      <header>
        <div className="practice-kicker">How the allocation algorithm works</div>
        <h2 id="practice-algorithm-title">It balances the whole room, not one object at a time.</h2>
        <p>Points become a personal measure of importance. The algorithm tests complete distributions, totals the value each person would receive, then favors the distribution that best serves everyone together.</p>
      </header>
      <ol>
        <li><span>1</span><div><strong>Private preferences</strong><p>Each heir distributes exactly 1,000 points. No heir sees another person’s sheet while allocation is open.</p></div></li>
        <li><span>2</span><div><strong>Complete distributions</strong><p>Items are evaluated as a complete allocation—not isolated contests. Six items and three heirs create 729 possible outcomes for the family.</p></div></li>
        <li><span>3</span><div><strong>Personal utility</strong><p>For each outcome, the system adds the points each heir placed on the items they would receive.</p></div></li>
        <li><span>4</span><div><strong>Nash balance</strong><p>Those totals are multiplied. A distribution that leaves one person with very little is penalized, even when another person receives a great deal.</p></div></li>
      </ol>
      <div className="rehearsal-equation">
        <div><span>Heir A receives</span><strong>620</strong></div>
        <i>×</i>
        <div><span>Heir B receives</span><strong>540</strong></div>
        <i>×</i>
        <div><span>Heir C receives</span><strong>480</strong></div>
        <i>=</i>
        <div><span>Balance score</span><strong>160,704,000</strong></div>
      </div>
      <details>
        <summary>What about highest points, ties, and impossible conflicts?</summary>
        <p><strong>Highest points:</strong> An item is not decided in isolation. Giving a shared favorite to someone’s second-highest scorer may produce a much stronger complete family distribution.</p>
        <p><strong>Ties:</strong> Recorded submission time, then a stable identifier, resolves ordinary mathematical ties without executor preference.</p>
        <p><strong>Deadlocks:</strong> When math cannot produce a responsible result, the session pauses for documented executor review rather than making a random choice.</p>
      </details>
    </section>
  );
}

function WelcomeStep({ config, context, itemCount, onContinue }) {
  return (
    <section className="rehearsal-welcome">
      {context.registered && (
        <div className="rehearsal-session-context">
          <span>Registered heir practice step</span>
          <strong>{context.session_title}</strong>
          <small>
            {context.completed_at
              ? 'You have completed this practice before. You may repeat it at any time.'
              : 'Complete this rehearsal before the Executor opens the real allocation.'}
          </small>
        </div>
      )}
      <div className="rehearsal-welcome-copy">
        <div className="practice-kicker">Complete process rehearsal</div>
        <h1>Practice once.<br />Begin the real process with confidence.</h1>
        <p>{config.welcome_message}</p>
        <button type="button" className="btn btn-primary btn-lg" onClick={onContinue}>
          Enter the practice estate
        </button>
        <small>About 8–12 minutes · Restart whenever you need · Nothing is submitted</small>
      </div>
      <div className="rehearsal-welcome-photo">
        <img src={config.items[0]?.image} alt="A sample keepsake from the fictional practice estate" />
        <div>
          <strong>{config.title}</strong>
          <span>{itemCount} fictional household items</span>
        </div>
      </div>
      <div className="rehearsal-journey-preview">
        <span>During this rehearsal, you will</span>
        <ol>
          <li>Browse the catalog and open item details</li>
          <li>Distribute exactly 1,000 private preference points</li>
          <li>Review and submit a practice allocation</li>
          <li>Experience the waiting period</li>
          <li>Read a complete result and fairness explanation</li>
        </ol>
      </div>
      <AlgorithmExplainer />
    </section>
  );
}

function CatalogStep({ config, points, viewedItems, onOpen, onContinue }) {
  const [category, setCategory] = useState('All');
  const items = config.items.filter((item) => item.enabled !== false);
  const categories = ['All', ...new Set(items.map((item) => item.category))];
  const visible = category === 'All' ? items : items.filter((item) => item.category === category);
  return (
    <section className="rehearsal-stage">
      <header className="rehearsal-stage-heading">
        <div>
          <div className="practice-kicker">Step 1 of 5 · Catalog</div>
          <h1>Take your time with the items.</h1>
          <p>Open any object to read its details and family story. In the real process, this is where you can listen, remember, and ask questions before assigning points.</p>
        </div>
        <div className="rehearsal-readiness">
          <strong>{viewedItems.size}</strong>
          <span>of {items.length} opened</span>
        </div>
      </header>
      <div className="rehearsal-filter-row">
        {categories.map((name) => (
          <button
            key={name}
            type="button"
            className={category === name ? 'is-active' : ''}
            onClick={() => setCategory(name)}
          >
            {name}
          </button>
        ))}
      </div>
      <div className="rehearsal-catalog-grid">
        {visible.map((item) => (
          <button type="button" key={item.id} className="rehearsal-catalog-item" onClick={() => onOpen(item)}>
            <div className="rehearsal-catalog-image">
              <img src={item.image} alt="" />
              {viewedItems.has(item.id) && <span>Viewed ✓</span>}
            </div>
            <div>
              <span>{item.category}</span>
              <h2>{item.title}</h2>
              <p>{item.description}</p>
              <strong>{item.value_range}</strong>
              {points[item.id] > 0 && <em>{points[item.id]} practice points</em>}
            </div>
          </button>
        ))}
      </div>
      <div className="rehearsal-stage-actions">
        <p>You do not need to want every item. Zero points is a meaningful choice.</p>
        <button type="button" className="btn btn-primary btn-lg" onClick={onContinue}>
          Continue to point allocation
        </button>
      </div>
    </section>
  );
}

function AllocationStep({ items, points, onChange, onSuggested, onBack, onContinue }) {
  const total = sumPoints(points);
  const remaining = 1000 - total;
  return (
    <section className="rehearsal-stage">
      <header className="rehearsal-stage-heading">
        <div>
          <div className="practice-kicker">Step 2 of 5 · Private preferences</div>
          <h1>Show what matters to you.</h1>
          <p>Points express relative importance—not price. Your fictional family members cannot see these choices while allocation is open.</p>
        </div>
        <div className={`rehearsal-points-meter ${remaining === 0 ? 'is-complete' : ''}`}>
          <strong>{remaining}</strong>
          <span>points remaining</span>
        </div>
      </header>
      <div className="rehearsal-allocation-help">
        <span aria-hidden="true">i</span>
        <p><strong>There is no correct strategy.</strong> Concentrate points on a few meaningful items or spread them out. The only rule is that your total must equal 1,000.</p>
        <button type="button" onClick={onSuggested}>Fill a sample distribution</button>
      </div>
      <div className="rehearsal-allocation-list">
        {items.map((item) => (
          <div className="rehearsal-allocation-row" key={item.id}>
            <img src={item.image} alt="" />
            <div>
              <span>{item.category}</span>
              <h2>{item.title}</h2>
              <p>{item.story}</p>
            </div>
            <input
              type="range"
              min="0"
              max="1000"
              step="10"
              value={points[item.id]}
              aria-label={`Points for ${item.title}`}
              onChange={(event) => onChange(item.id, Number(event.target.value))}
            />
            <label>
              <input
                type="number"
                min="0"
                max="1000"
                step="10"
                value={points[item.id]}
                aria-label={`Exact points for ${item.title}`}
                onChange={(event) => onChange(item.id, Number(event.target.value))}
              />
              <span>points</span>
            </label>
          </div>
        ))}
      </div>
      <div className="rehearsal-stage-actions">
        <button type="button" className="btn btn-secondary" onClick={onBack}>Back to catalog</button>
        <div>
          {remaining !== 0 && <span>Allocate the remaining {remaining} points to continue.</span>}
          <button type="button" className="btn btn-primary btn-lg" disabled={remaining !== 0} onClick={onContinue}>
            Review my practice choices
          </button>
        </div>
      </div>
    </section>
  );
}

function ReviewStep({ items, points, acknowledged, setAcknowledged, onBack, onSubmit }) {
  const ranked = [...items].sort((a, b) => points[b.id] - points[a.id]);
  return (
    <section className="rehearsal-stage rehearsal-review">
      <header className="rehearsal-stage-heading">
        <div>
          <div className="practice-kicker">Step 3 of 5 · Final review</div>
          <h1>Review before you submit.</h1>
          <p>In a real session, drafts can be changed until this moment. Submission locks your point sheet so the allocation can be run consistently.</p>
        </div>
      </header>
      <div className="rehearsal-review-layout">
        <div>
          <h2>Your 1,000-point preference sheet</h2>
          {ranked.map((item, index) => (
            <div className="rehearsal-review-row" key={item.id}>
              <span>{index + 1}</span>
              <img src={item.image} alt="" />
              <div><strong>{item.title}</strong><small>{item.category}</small></div>
              <b>{points[item.id]}</b>
            </div>
          ))}
        </div>
        <aside>
          <h2>Before submitting</h2>
          <ul>
            <li>Your points remain private during the active process.</li>
            <li>The algorithm evaluates everyone’s complete preference sheet.</li>
            <li>A high point value does not guarantee a particular item.</li>
            <li>Unresolvable conflicts pause for documented human review.</li>
          </ul>
          <label className="checkbox-label">
            <input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} />
            <span>I understand this is a fictional rehearsal and that a real submission becomes locked.</span>
          </label>
        </aside>
      </div>
      <div className="rehearsal-stage-actions">
        <button type="button" className="btn btn-secondary" onClick={onBack}>Change my points</button>
        <button type="button" className="btn btn-primary btn-lg" disabled={!acknowledged} onClick={onSubmit}>
          Submit practice allocation
        </button>
      </div>
    </section>
  );
}

function WaitingStep({ onResolve, running, error }) {
  return (
    <section className="rehearsal-stage rehearsal-waiting">
      <div className="practice-kicker">Step 4 of 5 · Waiting room</div>
      <h1>Your choices are safely submitted.</h1>
      <p>A real family may spend time here while everyone finishes independently. You would see progress—not anyone else’s points.</p>
      <div className="rehearsal-status-list">
        <div><span className="is-done">✓</span><div><strong>You</strong><small>Practice allocation submitted</small></div><b>Submitted</b></div>
        <div><span>J</span><div><strong>Jordan</strong><small>Fictional participant</small></div><b>Submitted</b></div>
        <div><span>C</span><div><strong>Casey</strong><small>Fictional participant</small></div><b>Submitted</b></div>
      </div>
      <div className="rehearsal-wait-note">
        <strong>What stays private?</strong>
        <p>You can see that Jordan and Casey finished, but not how they distributed their 1,000 points. Their example sheets will be revealed only after you continue, for teaching purposes.</p>
      </div>
      {error && <div className="banner banner-error">{error}</div>}
      <button type="button" className="btn btn-primary btn-lg" onClick={onResolve} disabled={running}>
        {running ? 'Running the allocation…' : 'All practice heirs are ready — run allocation'}
      </button>
    </section>
  );
}

function ResultStep({ items, valuations, result, context, completionState, onRestart }) {
  return (
    <section className="rehearsal-stage rehearsal-final-result">
      <header className="rehearsal-stage-heading">
        <div>
          <div className="practice-kicker">Step 5 of 5 · Practice result</div>
          <h1>See the whole distribution—and the reasoning behind it.</h1>
          <p>
            {result.engine === 'production'
              ? 'Your fictional preferences were processed by the same allocation engine used for the real session. It selected a complete distribution that balances all three preference sheets.'
              : `The teaching engine compared ${result.assignmentsToCheck.toLocaleString()} complete distributions and selected the one with the highest balance.`}
          </p>
        </div>
        <div className="rehearsal-result-seal"><span>✓</span> Complete</div>
      </header>
      <div className="rehearsal-result-columns">
        {PARTICIPANTS.map((participant) => {
          const received = items.filter((item) => result.assignment[item.id] === participant.id);
          return (
            <div key={participant.id}>
              <div className="rehearsal-result-person">
                <span>{participant.name.slice(0, 1)}</span>
                <div><h2>{participant.name}</h2><small>{participant.note}</small></div>
              </div>
              {received.map((item) => (
                <article key={item.id}>
                  <img src={item.image} alt="" />
                  <div><strong>{item.title}</strong><span>{valuations[participant.id][item.id]} points from {participant.name}</span></div>
                </article>
              ))}
              <footer><span>Personal value received</span><strong>{result.utility[participant.id]}</strong></footer>
            </div>
          );
        })}
      </div>
      <div className="rehearsal-proof">
        <div>
          <span className="practice-kicker">The fairness calculation</span>
          <h2>{PARTICIPANTS.map((p) => result.utility[p.id]).join(' × ')} = {result.product.toLocaleString()}</h2>
        </div>
        <p>This Nash product rewards distributions that give meaningful value to every participant. It does not simply award each item to its highest isolated point value.</p>
      </div>
      <details className="rehearsal-reveal">
        <summary>Reveal the fictional heirs’ point sheets</summary>
        <div>
          {PARTICIPANTS.slice(1).map((participant) => (
            <section key={participant.id}>
              <h3>{participant.name}’s 1,000 points</h3>
              {items.map((item) => (
                <p key={item.id}><span>{item.title}</span><strong>{valuations[participant.id][item.id]}</strong></p>
              ))}
            </section>
          ))}
        </div>
      </details>
      {result.tieEvents.length > 0 && (
        <div className="practice-tie-note">
          <strong>Deterministic tie record</strong>
          {result.tieEvents.map((event) => (
            <p key={event.item.id}>
              {event.item.title}: {event.tied.map((id) => PARTICIPANTS.find((p) => p.id === id).name).join(' and ')}
              {' '}both placed {event.points} points. {PARTICIPANTS.find((p) => p.id === event.winner).name} received it under the disclosed stable ordering.
            </p>
          ))}
        </div>
      )}
      <div className="rehearsal-learning-summary">
        <h2>You have now experienced the complete process.</h2>
        {context.registered && (
          <div className={`rehearsal-completion-record ${completionState}`}>
            <strong>
              {completionState === 'saved' && '✓ Practice completion recorded for this estate'}
              {completionState === 'saving' && 'Recording your practice completion…'}
              {completionState === 'error' && 'The rehearsal is complete, but completion could not be recorded.'}
            </strong>
            <span>
              {completionState === 'saved'
                ? 'The Executor can see that you finished—not the practice points you chose.'
                : 'Return to the result later or contact the Executor if this status does not update.'}
            </span>
          </div>
        )}
        <div className="rehearsal-learning-points">
          <p><strong>Private by design</strong><span>Point sheets stay hidden while allocation is open.</span></p>
          <p><strong>Balanced as a whole</strong><span>Every item and participant is considered together.</span></p>
          <p><strong>Auditable</strong><span>The inputs, result, tie rules, and interventions can be documented.</span></p>
        </div>
        <nav>
          <button type="button" className="btn btn-secondary" onClick={onRestart}>Practice again from the beginning</button>
          <Link to={context.registered ? '/dashboard' : '/login'} className="btn btn-primary">
            {context.registered ? 'Return to my estate dashboard' : 'I’m ready to sign in'}
          </Link>
        </nav>
      </div>
    </section>
  );
}

export default function AllocationPracticeRoom({ previewSessionId = null }) {
  const [config, setConfig] = useState(() => cloneSimulationConfig());
  const [context, setContext] = useState({
    config: cloneSimulationConfig(),
    registered: false,
    published: true,
    completed_at: null,
  });
  const [loadingContext, setLoadingContext] = useState(true);
  const [completionState, setCompletionState] = useState('idle');
  const [runState, setRunState] = useState('idle');
  const [runError, setRunError] = useState(null);
  const [step, setStep] = useState('welcome');
  const [maxStep, setMaxStep] = useState(0);
  const [points, setPoints] = useState(() => emptyPoints(DEFAULT_SIMULATION_CONFIG.items));
  const [viewedItems, setViewedItems] = useState(new Set());
  const [detailItem, setDetailItem] = useState(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [result, setResult] = useState(null);
  const [restartArmed, setRestartArmed] = useState(false);

  const items = useMemo(() => config.items.filter((item) => item.enabled !== false), [config]);

  useEffect(() => {
    let active = true;
    const contextPromise = previewSessionId
      ? loadSessionSimulationContext(previewSessionId)
      : loadHeirSimulationContext();
    contextPromise.then((loadedContext) => {
      if (!active) return;
      const loaded = loadedContext.config;
      const enabled = loaded.items?.filter((item) => item.enabled !== false) || [];
      const safeConfig = enabled.length >= 5 ? loaded : cloneSimulationConfig();
      setContext({ ...loadedContext, config: safeConfig });
      setConfig(safeConfig);
      setPoints(emptyPoints(safeConfig.items.filter((item) => item.enabled !== false)));
    }).finally(() => {
      if (active) setLoadingContext(false);
    });
    return () => { active = false; };
  }, [previewSessionId]);

  const goTo = (nextStep) => {
    const index = STEPS.findIndex((entry) => entry.id === nextStep);
    setStep(nextStep);
    setMaxStep((current) => Math.max(current, index));
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const restart = () => {
    if (!restartArmed && step !== 'result') {
      setRestartArmed(true);
      window.setTimeout(() => setRestartArmed(false), 4000);
      return;
    }
    setStep('welcome');
    setMaxStep(0);
    setPoints(emptyPoints(items));
    setViewedItems(new Set());
    setDetailItem(null);
    setAcknowledged(false);
    setResult(null);
    setCompletionState('idle');
    setRunState('idle');
    setRunError(null);
    setRestartArmed(false);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const changePoints = (itemId, requested) => {
    const safe = Number.isFinite(requested) ? Math.max(0, Math.min(1000, requested)) : 0;
    setPoints((current) => {
      const without = sumPoints(current) - current[itemId];
      return { ...current, [itemId]: Math.min(safe, 1000 - without) };
    });
  };

  const useSuggested = () => {
    const weights = [310, 210, 170, 130, 110, 70, 0, 0, 0, 0];
    const next = {};
    items.forEach((item, index) => { next[item.id] = weights[index] || 0; });
    const total = sumPoints(next);
    if (total < 1000 && items[0]) next[items[0].id] += 1000 - total;
    setPoints(next);
  };

  const runAllocation = async () => {
    const valuations = {
      you: points,
      jordan: Object.fromEntries(items.map((item) => [item.id, item.companion_points?.jordan || 0])),
      casey: Object.fromEntries(items.map((item) => [item.id, item.companion_points?.casey || 0])),
    };
    setRunState('running');
    setRunError(null);
    let solvedResult;
    if (context.registered) {
      try {
        const response = await fetch('/api/heirs/me/simulation/solve', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify({ points }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          const serviceMessage = response.status >= 500
            ? 'The practice service briefly lost its connection. Please try again.'
            : 'The practice allocation could not be run.';
          throw new Error(data.detail || serviceMessage);
        }
        solvedResult = data;
      } catch (error) {
        setRunState('error');
        setRunError(error.message);
        return;
      }
    } else {
      solvedResult = { ...simulateFullAllocation(items, valuations), valuations, engine: 'teaching' };
    }
    setResult(solvedResult);
    setRunState('complete');
    goTo('result');
    if (context.registered && context.published) {
      setCompletionState('saving');
      try {
        const response = await fetch('/api/heirs/me/simulation/complete', {
          method: 'POST',
          credentials: 'same-origin',
        });
        if (!response.ok) throw new Error('Completion could not be recorded.');
        const data = await response.json();
        setCompletionState('saved');
        setContext((current) => ({ ...current, completed_at: data.completed_at }));
      } catch {
        setCompletionState('error');
      }
    }
  };

  const openItem = (item) => {
    setViewedItems((current) => new Set([...current, item.id]));
    setDetailItem(item);
  };

  if (loadingContext) {
    return (
      <main className="practice-room rehearsal rehearsal-loading">
        <p>Preparing your practice estate…</p>
      </main>
    );
  }

  if (context.registered && !context.published) {
    return (
      <main className="practice-room rehearsal rehearsal-not-ready">
        <div>
          <div className="practice-kicker">Registered heir practice step</div>
          <h1>Your practice allocation is being prepared.</h1>
          <p>The Executor will choose the fictional items and publish the rehearsal before the real allocation begins. Nothing is required from you yet.</p>
          <Link className="btn btn-primary" to="/dashboard">Return to my estate dashboard</Link>
        </div>
      </main>
    );
  }

  return (
    <main className="practice-room rehearsal">
      <PracticeHeader step={step} onRestart={restart} restartArmed={restartArmed} registered={context.registered} />
      <StepRail currentStep={step} maxStep={maxStep} onStep={goTo} />
      {step === 'welcome' && <WelcomeStep config={config} context={context} itemCount={items.length} onContinue={() => goTo('catalog')} />}
      {step === 'catalog' && (
        <CatalogStep
          config={{ ...config, items }}
          points={points}
          viewedItems={viewedItems}
          onOpen={openItem}
          onContinue={() => goTo('allocate')}
        />
      )}
      {step === 'allocate' && (
        <AllocationStep
          items={items}
          points={points}
          onChange={changePoints}
          onSuggested={useSuggested}
          onBack={() => goTo('catalog')}
          onContinue={() => goTo('review')}
        />
      )}
      {step === 'review' && (
        <ReviewStep
          items={items}
          points={points}
          acknowledged={acknowledged}
          setAcknowledged={setAcknowledged}
          onBack={() => goTo('allocate')}
          onSubmit={() => goTo('waiting')}
        />
      )}
      {step === 'waiting' && (
        <WaitingStep
          onResolve={runAllocation}
          running={runState === 'running'}
          error={runError}
        />
      )}
      {step === 'result' && result && (
        <ResultStep
          items={items}
          valuations={result.valuations}
          result={result}
          context={context}
          completionState={completionState}
          onRestart={restart}
        />
      )}
      <ItemDetail
        item={detailItem}
        points={detailItem ? points[detailItem.id] : 0}
        onClose={() => setDetailItem(null)}
        onAllocate={() => {
          setDetailItem(null);
          goTo('allocate');
        }}
      />
    </main>
  );
}
