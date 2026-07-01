import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useMediationStore } from '../store/useMediationStore';
import ModelTransparencyModal from './ModelTransparencyModal';

export default function FAQDrawer({ isOpen, onClose }) {
  const sessionId = useMediationStore((s) => s.session_id);
  const [estateFaqs, setEstateFaqs] = useState([]);
  const [loadingEstateFaqs, setLoadingEstateFaqs] = useState(false);
  const [openItem, setOpenItem] = useState(null); // id of open faq item
  const [showTransparency, setShowTransparency] = useState(false);

  useEffect(() => {
    if (isOpen && sessionId) {
      fetchEstateFaqs();
    }
  }, [isOpen, sessionId]);

  async function fetchEstateFaqs() {
    try {
      setLoadingEstateFaqs(true);
      const res = await fetch(`/api/sessions/${sessionId}/faqs`);
      if (res.ok) {
        const data = await res.json();
        setEstateFaqs(data);
      }
    } catch (err) {
      console.error('Failed to load estate specific FAQs', err);
    } finally {
      setLoadingEstateFaqs(false);
    }
  }

  if (!isOpen) return null;

  const toggleItem = (itemId) => {
    setOpenItem((prev) => (prev === itemId ? null : itemId));
  };

  const staticFaqs = [
    {
      id: 's1',
      question: 'How does the point allocation system work?',
      answer: (
        <div>
          <p>You are given a pool of <strong>1,000 points</strong> to distribute across the active estate catalog.</p>
          <ul style={{ paddingLeft: 'var(--space-md)', marginBottom: 'var(--space-md)' }}>
            <li>Points represent your personal preference and sentimental attachment to items.</li>
            <li>You can assign all 1,000 points to a single highly desired keepsake (e.g., grandfather clock), spread them evenly across many small items, or leave items at 0 points if you do not want them.</li>
            <li>Your total allocated points must equal <strong>exactly 1,000</strong> before you can submit.</li>
          </ul>
        </div>
      ),
    },
    {
      id: 's2',
      question: 'Are my points visible to my family members?',
      answer: (
        <p>
          <strong>No.</strong> Individual point allocations are kept <strong>strictly private</strong> during the active mediation phase. This prevents tactical bidding, pressure, or conflict. Family members can only see progress checkmarks (indicating whether you have submitted), never your actual points.
        </p>
      ),
    },
    {
      id: 's3',
      question: 'Can I change my selections after adjusting the sliders?',
      answer: (
        <p>
          Yes. Your slider adjustments are automatically saved as <strong>drafts</strong> as you work. You can close your browser and return on any device without losing progress. However, once you click the final <strong>"Submit Valuations"</strong> button, your selections are locked and submitted to the division solver.
        </p>
      ),
    },
    {
      id: 's4',
      question: 'What is the AI Mediator and what does it do?',
      answer: (
        <div>
          <p>The AI Mediator is a local, secure assistant designed to guide you through asset catalog details, answer questions about item histories, and provide a quiet space to discuss sentimental stories.</p>
          <ul style={{ paddingLeft: 'var(--space-md)', marginBottom: 'var(--space-md)' }}>
            <li>The Mediator is an automated AI assistant.</li>
            <li>Your chat transcripts are <strong>completely confidential</strong> to you; they are blocked from the Executor and other heirs to ensure a safe space.</li>
            <li>The Mediator has no authority to distribute items; its role is strictly supportive.</li>
          </ul>
        </div>
      ),
    },
    {
      id: 's5',
      question: 'What is a "Grief Pause"?',
      answer: (
        <p>
          Mediation can be emotionally overwhelming. If you or another heir clicks the <em>"Request Help"</em> button and requests a break, the Executor can trigger a <strong>Grief Pause</strong>. This freezes all points sliders and chat inputs globally, allowing the family to take a step back, rest, and communicate offline. Pending invitation countdowns are automatically extended for the duration of the pause.
        </p>
      ),
    },
    {
      id: 's6',
      question: 'How does the system decide who gets what?',
      answer: (
        <div>
          <p>Once everyone submits, the system runs a fair-division algorithm called <strong>Maximum Nash Welfare (MNW)</strong>.</p>
          <ul style={{ paddingLeft: 'var(--space-md)', marginBottom: 'var(--space-md)' }}>
            <li>The math aims to maximize the collective happiness of the family.</li>
            <li>Unlike auction systems where one person wins everything, MNW balances allocations so that every heir receives a fair, high-sentiment share based on their points, minimizing situations where someone receives nothing.</li>
            <li><strong>Resolving Ties</strong>: If two or more heirs allocate the exact same points to an item and the system needs to break a tie, the item is awarded to the heir who finalized and submitted their choices first. If both heirs submitted at the exact same time, the system resolves it alphabetically by their user identifier. This ensures a deterministic, completely impartial outcome with no executor favoritism.</li>
          </ul>
        </div>
      ),
    },
    {
      id: 's7',
      question: 'Why do I need to verify my legal name, relationship, DOB, and upload an ID?',
      answer: (
        <div>
          <p>Because this system compiles the <strong>Final Probate Audit Ledger</strong> and legal waivers (like the Abstention Waiver) to be formally filed with a probate court, the Executor has a fiduciary duty to confirm that allocations and waivers are executed by the actual, verified beneficiaries.</p>
          <ul style={{ paddingLeft: 'var(--space-md)', marginBottom: 'var(--space-md)' }}>
            <li><strong>The Verification Hold</strong>: While your ID verification is pending or if a correction is requested, your dashboard is placed on a read-only <strong>"Profile Hold"</strong> state. During this time, you can browse assets but cannot adjust points sliders or use the mediator chat, preventing invalid entries from being signed on the ledger.</li>
            <li><strong>Privacy Protections</strong>: Your uploaded ID document is encrypted immediately with a local AES-256 key. It is temporarily stored on the local Raspberry Pi server and is <strong>permanently deleted</strong> (purged entirely from the filesystem) as soon as the Executor either approves or rejects your profile. The system is local-first, runs entirely offline, and never sends your ID to the cloud.</li>
          </ul>
        </div>
      ),
    },
  ];

  return (
    <>
      <div className="help-drawer-backdrop" onClick={onClose} data-testid="drawer-backdrop" />
      <div className="help-drawer" role="dialog" aria-modal="true" data-testid="faq-drawer">
        <div className="help-drawer-header">
          <h3 style={{ fontFamily: 'var(--font-serif)', margin: 0 }}>Help & FAQs</h3>
          <button className="close-btn" onClick={onClose} aria-label="Close Help">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>

        <div className="help-drawer-body">
          <h4 className="drawer-section-title">Estate Specific Guidelines</h4>
          {loadingEstateFaqs ? (
            <p className="text-xs text-muted" style={{ padding: '0 var(--space-sm)' }}>Loading estate instructions...</p>
          ) : estateFaqs.length === 0 ? (
            <p className="text-xs text-muted" style={{ padding: '0 var(--space-sm)', fontStyle: 'italic' }}>
              No custom guidelines have been published by the Executor yet.
            </p>
          ) : (
            <div className="faq-accordion" data-testid="estate-faqs">
              {estateFaqs.map((faq) => (
                <div key={faq.id} className="accordion-item">
                  <button
                    className="accordion-trigger"
                    onClick={() => toggleItem(`e-${faq.id}`)}
                    aria-expanded={openItem === `e-${faq.id}`}
                  >
                    <span>{faq.question}</span>
                    <span>{openItem === `e-${faq.id}` ? '−' : '+'}</span>
                  </button>
                  {openItem === `e-${faq.id}` && (
                    <div className="accordion-content">
                      <p style={{ margin: 0 }}>{faq.answer}</p>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          <h4 className="drawer-section-title">General Mediation & Math FAQs</h4>
          <div className="faq-accordion" data-testid="static-faqs">
            {staticFaqs.map((faq) => (
              <div key={faq.id} className="accordion-item">
                <button
                  className="accordion-trigger"
                  onClick={() => toggleItem(faq.id)}
                  aria-expanded={openItem === faq.id}
                >
                  <span>{faq.question}</span>
                  <span>{openItem === faq.id ? '−' : '+'}</span>
                </button>
                {openItem === faq.id && (
                  <div className="accordion-content">
                    {faq.answer}
                    {faq.id === 's6' && (
                      <Link
                        className="btn btn-secondary btn-sm"
                        to="/allocation-practice"
                        onClick={onClose}
                        style={{ marginTop: 'var(--space-sm)' }}
                      >
                        Try a private practice example
                      </Link>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>

          <div style={{ padding: 'var(--space-md) 0', borderTop: '1px solid var(--color-border)', marginTop: 'var(--space-md)' }}>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => setShowTransparency(true)}
              data-testid="transparency-trigger"
              type="button"
              style={{ width: '100%', textAlign: 'left' }}
            >
              AI Model Details & Training Transparency
            </button>
            <p className="text-xs text-muted" style={{ marginTop: 'var(--space-xs)' }}>
              View model parameters, licensing, and training data provenance per California AB 2013.
            </p>
          </div>
        </div>
      </div>

      <ModelTransparencyModal
        isOpen={showTransparency}
        onClose={() => setShowTransparency(false)}
      />
    </>
  );
}
