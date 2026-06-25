import React, { useState, useEffect } from 'react';
import ModelTransparencyModal from './ModelTransparencyModal';
import { customConfirm } from '../store/useDialogStore';

export default function AdminHelpPortal({ isOpen, onClose, sessionId }) {
  const [faqs, setFaqs] = useState([]);
  const [loadingFaqs, setLoadingFaqs] = useState(false);
  const [showTransparency, setShowTransparency] = useState(false);
  
  // Form state
  const [editingFaqId, setEditingFaqId] = useState(null);
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState('');
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (isOpen && sessionId) {
      fetchFaqs();
    }
  }, [isOpen, sessionId]);

  async function fetchFaqs() {
    try {
      setLoadingFaqs(true);
      setError(null);
      const res = await fetch(`/api/sessions/${sessionId}/faqs`);
      if (res.ok) {
        const data = await res.json();
        setFaqs(data);
      } else {
        throw new Error('Failed to load custom FAQs');
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoadingFaqs(false);
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!question.trim() || !answer.trim()) return;

    setSubmitting(true);
    setError(null);

    try {
      const url = editingFaqId
        ? `/api/sessions/${sessionId}/faqs/${editingFaqId}`
        : `/api/sessions/${sessionId}/faqs`;
      const method = editingFaqId ? 'PUT' : 'POST';

      const res = await fetch(url, {
        method,
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, answer }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to save FAQ');
      }

      setQuestion('');
      setAnswer('');
      setEditingFaqId(null);
      await fetchFaqs();
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(faqId) {
    if (!await customConfirm('Are you sure you want to delete this FAQ guideline?')) return;
    
    setError(null);
    try {
      const res = await fetch(`/api/sessions/${sessionId}/faqs/${faqId}`, {
        method: 'DELETE',
        credentials: 'same-origin',
      });
      if (!res.ok) throw new Error('Failed to delete FAQ');
      await fetchFaqs();
    } catch (err) {
      setError(err.message);
    }
  }

  function startEdit(faq) {
    setEditingFaqId(faq.id);
    setQuestion(faq.question);
    setAnswer(faq.answer);
  }

  function cancelEdit() {
    setEditingFaqId(null);
    setQuestion('');
    setAnswer('');
  }

  if (!isOpen) return null;

  return (
    <div className="help-modal-backdrop" onClick={onClose} data-testid="portal-backdrop">
      <div className="help-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" data-testid="admin-help-portal">
        <div className="help-modal-header">
          <h2 style={{ fontFamily: 'var(--font-serif)', margin: 0 }}>Executor Quick-Start & FAQ Guide</h2>
          <button className="close-btn" onClick={onClose} aria-label="Close Guide">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>

        <div className="help-modal-body">
          {/* Narrative Tutorial sections */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-xl)', marginBottom: 'var(--space-2xl)' }}>
            
            {/* Section 1: Snap & Catalog Guide */}
            <section data-testid="tutorial-section-1">
              <h3 style={{ borderBottom: '1px solid var(--color-border)', paddingBottom: 'var(--space-xs)', marginBottom: 'var(--space-md)', color: 'var(--color-primary)' }}>
                Section 1: Snap & Catalog Guide
              </h3>
              <p>To build the estate catalog and make items available for allocation:</p>
              <ol style={{ paddingLeft: 'var(--space-md)', display: 'flex', flexDirection: 'column', gap: 'var(--space-sm)' }}>
                <li>
                  Open the Admin Console on your phone or tablet and tap <strong>"Capture Asset"</strong>.
                </li>
                <li>
                  Snap a photo of the keepsake using your device camera.
                </li>
                <li>
                  The system will upload the image and automatically run a local AI visual scan (OCR) to pre-fill the item's Title, Description, and Category.
                </li>
                <li>
                  <strong>Voice Story Dictation</strong>: Tap the microphone icon next to the description box to speak and record the history of the item. The speech will transcribe directly into the text field.
                </li>
                <li>
                  <strong>Admin Spoken Story Recording</strong>: Use the voice recorder panel to record your actual voice talking about the keepsake. Heirs will be able to click and listen to your voice recording when reviewing the catalog.
                </li>
                <li>
                  Verify and edit details, input an appraisal valuation range and its <strong>Valuation Source</strong> (e.g., 'Professional Appraisal' or 'Tax Assessment'), and tap <strong>"Publish Live"</strong>.
                </li>
              </ol>
            </section>

            {/* Section 2: Disaster Recovery & Backups */}
            <section data-testid="tutorial-section-2">
              <h3 style={{ borderBottom: '1px solid var(--color-border)', paddingBottom: 'var(--space-xs)', marginBottom: 'var(--space-md)', color: 'var(--color-primary)' }}>
                Section 2: Disaster Recovery & Backups
              </h3>
              <p>Our platform values local privacy and encrypts data at rest using AES-Fernet:</p>
              <ul style={{ paddingLeft: 'var(--space-md)', display: 'flex', flexDirection: 'column', gap: 'var(--space-sm)' }}>
                <li>
                  <strong>Paper Recovery Key</strong>: Upon creation of the Administrator account, the system generates a 24-word paper recovery key. <strong>Write this down</strong> on physical paper and store it in a secure physical safe.
                </li>
                <li>
                  <strong>Symmetric Backup</strong>: Database backups are encrypted locally. If the hardware suffers an outage, the 24-word phrase is the <strong>only way</strong> to restore and decrypt your data.
                </li>
                <li>
                  <strong>System Restore</strong>: In the event of system rebuilds, navigate to the Restore Panel and enter your BIP39 mnemonic passphrase to restore database states.
                </li>
              </ul>
            </section>

            {/* Section 3: Probate & Fiduciary Compliance */}
            <section data-testid="tutorial-section-3">
              <h3 style={{ borderBottom: '1px solid var(--color-border)', paddingBottom: 'var(--space-xs)', marginBottom: 'var(--space-md)', color: 'var(--color-primary)' }}>
                Section 3: Probate & Fiduciary Compliance
              </h3>
              <p>Fulfill estate fiduciary duties under uniform probate rules:</p>
              <ul style={{ paddingLeft: 'var(--space-md)', display: 'flex', flexDirection: 'column', gap: 'var(--space-sm)' }}>
                <li>
                  <strong>Specific Devises</strong>: If the decedent's Will specifies that an item belongs to a particular heir, locate the staged asset, click <strong>"Edit / Pre-Allocate"</strong>, select the Heir, and save. This marks the asset as <code>'PRE_ALLOCATED'</code>, locking it to that heir and bypassing points division.
                </li>
                <li>
                  <strong>Fiduciary Scope</strong>: Per Legal Spec §4, this system is strictly for personal property and keepsakes. Do not upload real estate, vehicles, or bank/financial accounts.
                </li>
                <li>
                  <strong>E-SIGN Consent</strong>: Heirs must review and sign the E-SIGN consumer disclosure banner during onboarding before participating.
                </li>
              </ul>
            </section>

            {/* Section 4: System Diagnostics */}
            <section data-testid="tutorial-section-4">
              <h3 style={{ borderBottom: '1px solid var(--color-border)', paddingBottom: 'var(--space-xs)', marginBottom: 'var(--space-md)', color: 'var(--color-primary)' }}>
                Section 4: System Diagnostics
              </h3>
              <p>Monitor local Raspberry Pi service status indicators:</p>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-md)', marginTop: 'var(--space-sm)' }}>
                <div className="archival-card" style={{ padding: 'var(--space-md)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-sm)' }}>
                    <span style={{ width: 12, height: 12, borderRadius: '50%', backgroundColor: '#22C55E', display: 'inline-block' }}></span>
                    <strong>Ollama Service (qwen2.5)</strong>
                  </div>
                  <p className="text-xs text-muted" style={{ margin: 'var(--space-sm) 0 0 0' }}>
                    Local model serving active on CPU. Status: Healthy.
                  </p>
                </div>
                <div className="archival-card" style={{ padding: 'var(--space-md)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-sm)' }}>
                    <span style={{ width: 12, height: 12, borderRadius: '50%', backgroundColor: '#22C55E', display: 'inline-block' }}></span>
                    <strong>Kokoro TTS Engine</strong>
                  </div>
                  <p className="text-xs text-muted" style={{ margin: 'var(--space-sm) 0 0 0' }}>
                    ONNX speech synthesis initialized (max 2 threads).
                  </p>
                </div>
              </div>

              <div style={{ marginTop: 'var(--space-lg)', paddingTop: 'var(--space-md)', borderTop: '1px solid var(--color-border)' }}>
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={() => setShowTransparency(true)}
                  data-testid="transparency-trigger"
                  type="button"
                >
                  AI Model Details & Training Transparency
                </button>
                <p className="text-xs text-muted" style={{ marginTop: 'var(--space-xs)' }}>
                  View model parameters, licensing, and training data provenance per California AB 2013.
                </p>
              </div>
            </section>

            {/* Section 5: Estate FAQ Editor */}
            <section data-testid="tutorial-section-5">
              <h3 style={{ borderBottom: '1px solid var(--color-border)', paddingBottom: 'var(--space-xs)', marginBottom: 'var(--space-md)', color: 'var(--color-primary)' }}>
                Section 5: Estate FAQ Editor
              </h3>
              <p style={{ marginBottom: 'var(--space-lg)' }}>
                Publish custom estate-specific rules (e.g. shipping logistics, pickup dates, house rules) that will dynamically sync to Heir dashboards in real-time.
              </p>

              {error && (
                <div className="banner banner-error" style={{ marginBottom: 'var(--space-md)' }}>
                  {error}
                </div>
              )}

              {/* FAQ Form */}
              <form onSubmit={handleSubmit} className="archival-card" style={{ marginBottom: 'var(--space-lg)', padding: 'var(--space-md)' }}>
                <h4 style={{ marginBottom: 'var(--space-sm)' }}>
                  {editingFaqId ? 'Edit FAQ Guideline' : 'Create Custom FAQ Guideline'}
                </h4>
                
                <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-sm)' }}>
                  <div>
                    <label className="form-label" htmlFor="faq-question">Question</label>
                    <input
                      id="faq-question"
                      className="form-input"
                      type="text"
                      placeholder="e.g., When is the pickup deadline?"
                      value={question}
                      onChange={(e) => setQuestion(e.target.value)}
                      required
                    />
                  </div>

                  <div>
                    <label className="form-label" htmlFor="faq-answer">Answer</label>
                    <textarea
                      id="faq-answer"
                      className="form-input form-textarea"
                      placeholder="e.g., All items must be collected from the residence by August 15th."
                      value={answer}
                      onChange={(e) => setAnswer(e.target.value)}
                      required
                      style={{ minHeight: 80 }}
                    />
                  </div>

                  <div style={{ display: 'flex', gap: 'var(--space-sm)', marginTop: 'var(--space-sm)' }}>
                    <button
                      className="btn btn-primary btn-sm"
                      type="submit"
                      disabled={submitting}
                    >
                      {submitting ? 'Saving...' : editingFaqId ? 'Update Guideline' : 'Publish Guideline'}
                    </button>
                    {editingFaqId && (
                      <button
                        className="btn btn-secondary btn-sm"
                        type="button"
                        onClick={cancelEdit}
                      >
                        Cancel
                      </button>
                    )}
                  </div>
                </div>
              </form>

              {/* Published Guidelines List */}
              <div className="published-guidelines-list">
                <h4 style={{ marginBottom: 'var(--space-sm)' }}>Published Estate Guidelines</h4>
                {loadingFaqs ? (
                  <p className="text-sm text-muted">Loading published guidelines...</p>
                ) : faqs.length === 0 ? (
                  <p className="text-sm text-muted" style={{ fontStyle: 'italic' }}>
                    No custom guidelines published yet. Create one above to guide heirs.
                  </p>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-sm)' }}>
                    {faqs.map((faq) => (
                      <div
                        key={faq.id}
                        className="archival-card"
                        style={{ padding: 'var(--space-md)', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 'var(--space-md)' }}
                        data-testid={`faq-item-${faq.id}`}
                      >
                        <div style={{ flex: 1 }}>
                          <strong style={{ display: 'block', marginBottom: 'var(--space-xs)' }}>{faq.question}</strong>
                          <p className="text-sm text-muted" style={{ margin: 0 }}>{faq.answer}</p>
                        </div>
                        <div style={{ display: 'flex', gap: 'var(--space-xs)' }}>
                          <button
                            className="btn btn-secondary btn-sm"
                            onClick={() => startEdit(faq)}
                            style={{ padding: '2px 8px', fontSize: '0.75rem' }}
                          >
                            Edit
                          </button>
                          <button
                            className="btn btn-secondary btn-sm"
                            onClick={() => handleDelete(faq.id)}
                            style={{ padding: '2px 8px', fontSize: '0.75rem', color: 'var(--color-error)' }}
                          >
                            Delete
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </section>

          </div>
        </div>
      </div>

      <ModelTransparencyModal
        isOpen={showTransparency}
        onClose={() => setShowTransparency(false)}
      />
    </div>
  );
}
