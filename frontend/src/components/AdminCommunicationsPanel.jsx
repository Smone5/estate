import React, { useEffect, useMemo, useState, useRef, useCallback } from 'react';
import { useMediationStore } from '../store/useMediationStore';

function formatTime(value) {
  if (!value) return '';
  try {
    const d = new Date(value);
    const now = new Date();
    const diffMs = now - d;
    const diffDays = Math.floor(diffMs / 86400000);
    if (diffDays === 0) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (diffDays === 1) return 'Yesterday ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (diffDays < 7) return d.toLocaleDateString([], { weekday: 'short' }) + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return value;
  }
}

function formatDateTime(value) {
  if (!value) return 'Not recorded';
  try { return new Date(value).toLocaleString(); } catch { return value; }
}

function statusClass(status) {
  if (status === 'RESOLVED') return 'resolved';
  if (status === 'RESPONDED') return 'responded';
  return 'open';
}

function heirDisplayName(heir) {
  return [
    heir.legal_first_name,
    heir.legal_middle_name,
    heir.legal_last_name,
  ].filter(Boolean).join(' ') || heir.username || heir.email || 'Unknown heir';
}

function isExecutorMessage(ticket) {
  return ticket?.initiator_role === 'ADMIN';
}

/**
 * Flattens an array of SupportRequest tickets into a chronological list
 * of individual message events for display as chat bubbles.
 *
 * Each ticket may contain up to TWO messages:
 *  1. The initial message (from heir or admin)
 *  2. The admin reply (if present on a heir-initiated ticket)
 */
function flattenTicketsToMessages(tickets) {
  const messages = [];

  for (const ticket of tickets) {
    if (isExecutorMessage(ticket)) {
      // Admin-initiated direct message
      messages.push({
        id: `${ticket.id}-direct`,
        ticketId: ticket.id,
        text: ticket.admin_response || ticket.message,
        imageUri: ticket.admin_image_uri,
        from: 'admin',
        timestamp: ticket.created_at,
        status: ticket.status,
        ticket,
      });
    } else {
      // Heir-initiated request: show heir's message bubble
      messages.push({
        id: `${ticket.id}-heir`,
        ticketId: ticket.id,
        text: ticket.message,
        imageUri: ticket.heir_image_uri,
        from: 'heir',
        timestamp: ticket.created_at,
        status: ticket.status,
        ticket,
      });

      // If admin has replied, show reply as a separate outgoing bubble
      if (ticket.admin_response || ticket.admin_image_uri) {
        messages.push({
          id: `${ticket.id}-admin-reply`,
          ticketId: ticket.id,
          text: ticket.admin_response,
          imageUri: ticket.admin_image_uri,
          from: 'admin',
          timestamp: ticket.responded_at || ticket.created_at,
          status: ticket.status,
          ticket,
          isReply: true,
        });
      }
    }
  }

  // Sort all events chronologically (oldest first → newest at bottom)
  return messages.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
}

export default function AdminCommunicationsPanel({ sessionId, heirs = [] }) {
  const supportRefreshToken = useMediationStore((s) => s.supportRefreshToken);

  const [tickets, setTickets] = useState([]);
  const [selectedHeirId, setSelectedHeirId] = useState(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [filterMode, setFilterMode] = useState('ALL');
  const [isAuditOpen, setIsAuditOpen] = useState(false);
  const [auditTicketId, setAuditTicketId] = useState(null);

  const [replyText, setReplyText] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [sending, setSending] = useState(false);
  const [resolving, setResolving] = useState(false);

  const [attachmentFile, setAttachmentFile] = useState(null);
  const [attachmentPreviewUrl, setAttachmentPreviewUrl] = useState(null);

  const fileInputRef = useRef(null);

  const timelineRef = useRef(null);
  const textareaRef = useRef(null);

  // ── Eligible heirs ──────────────────────────────────────────────────────────
  const eligibleHeirs = useMemo(() => {
    const list = [...heirs.filter((heir) => (heir.role || 'HEIR') === 'HEIR')];
    tickets.forEach((ticket) => {
      if (ticket.heir_id && !list.some((h) => h.id === ticket.heir_id)) {
        list.push({
          id: ticket.heir_id,
          username: ticket.username || 'heir',
          email: ticket.email || '',
          legal_first_name: ticket.legal_name || ticket.username || 'Heir',
          legal_middle_name: '',
          legal_last_name: '',
          role: 'HEIR',
        });
      }
    });
    return list;
  }, [heirs, tickets]);

  // ── Fetch tickets ───────────────────────────────────────────────────────────
  const fetchTickets = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/sessions/${sessionId}/help`, {
        credentials: 'same-origin',
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Failed to load messages (${res.status})`);
      }
      const data = await res.json();
      setTickets(Array.isArray(data) ? data : []);
    } catch (err) {
      setError(err.message || 'Failed to load communications');
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    fetchTickets();
  }, [fetchTickets, supportRefreshToken]);

  // ── Polling fallback: refresh every 20s while the panel is mounted ─────────
  useEffect(() => {
    if (!sessionId) return;
    const id = setInterval(fetchTickets, 20000);
    return () => clearInterval(id);
  }, [sessionId, fetchTickets]);

  // ── Visibility refresh: immediately re-fetch when user switches back ────────
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible') fetchTickets();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, [fetchTickets]);

  useEffect(() => {
    return () => {
      if (attachmentPreviewUrl) URL.revokeObjectURL(attachmentPreviewUrl);
    };
  }, [attachmentPreviewUrl]);

  function handleAttachmentSelect(e) {
    const file = e.target.files[0];
    if (!file) return;
    if (attachmentPreviewUrl) URL.revokeObjectURL(attachmentPreviewUrl);
    setAttachmentFile(file);
    setAttachmentPreviewUrl(URL.createObjectURL(file));
  }

  function clearAttachment() {
    if (attachmentPreviewUrl) URL.revokeObjectURL(attachmentPreviewUrl);
    setAttachmentFile(null);
    setAttachmentPreviewUrl(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
  }

  // ── Heir conversation summaries ─────────────────────────────────────────────
  const heirConversations = useMemo(() => {
    return eligibleHeirs.map((heir) => {
      const heirTickets = tickets.filter((t) => t.heir_id === heir.id);
      const openCount = heirTickets.filter(
        (t) => t.status === 'OPEN' && t.initiator_role === 'HEIR',
      ).length;
      const sorted = [...heirTickets].sort(
        (a, b) => new Date(b.created_at) - new Date(a.created_at),
      );
      const lastMsg = sorted[0] || null;
      const lastMsgText = lastMsg
        ? isExecutorMessage(lastMsg)
          ? `You: ${lastMsg.admin_response || lastMsg.message}`
          : lastMsg.message
        : null;

      return { heir, openCount, lastMsg, lastMsgText };
    });
  }, [eligibleHeirs, tickets]);

  const filteredConversations = useMemo(() => {
    return heirConversations.filter((conv) => {
      const matchesSearch = heirDisplayName(conv.heir)
        .toLowerCase()
        .includes(searchTerm.toLowerCase());
      if (!matchesSearch) return false;
      if (filterMode === 'OPEN') return conv.openCount > 0;
      if (filterMode === 'RESOLVED') {
        const heirTickets = tickets.filter((t) => t.heir_id === conv.heir.id);
        return heirTickets.length > 0 && conv.openCount === 0;
      }
      return true;
    });
  }, [heirConversations, searchTerm, filterMode, tickets]);

  // Auto-select first heir
  useEffect(() => {
    if (
      filteredConversations.length > 0 &&
      (!selectedHeirId ||
        !filteredConversations.some((c) => c.heir.id === selectedHeirId))
    ) {
      setSelectedHeirId(filteredConversations[0].heir.id);
    }
  }, [filteredConversations, selectedHeirId]);

  const selectedHeir = useMemo(
    () => eligibleHeirs.find((h) => h.id === selectedHeirId) || null,
    [eligibleHeirs, selectedHeirId],
  );

  // ── Active tickets for selected heir ───────────────────────────────────────
  const activeTickets = useMemo(() => {
    if (!selectedHeirId) return [];
    return tickets
      .filter((t) => t.heir_id === selectedHeirId)
      .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
  }, [tickets, selectedHeirId]);

  // Flatten into virtual message list
  const virtualMessages = useMemo(
    () => flattenTicketsToMessages(activeTickets),
    [activeTickets],
  );

  // Find the most recent OPEN heir ticket (for reply routing)
  const openHeirTicket = useMemo(() => {
    return (
      activeTickets
        .filter((t) => t.initiator_role === 'HEIR' && t.status === 'OPEN')
        .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))[0] ||
      null
    );
  }, [activeTickets]);

  // Audit ticket for the panel
  const auditTicket = useMemo(() => {
    if (auditTicketId) return activeTickets.find((t) => t.id === auditTicketId) || null;
    return null;
  }, [activeTickets, auditTicketId]);

  // ── Scroll to bottom ────────────────────────────────────────────────────────
  useEffect(() => {
    if (timelineRef.current) {
      timelineRef.current.scrollTop = timelineRef.current.scrollHeight;
    }
  }, [virtualMessages]);

  // ── Reset on heir change ────────────────────────────────────────────────────
  useEffect(() => {
    setReplyText('');
    setActionError(null);
    setAuditTicketId(null);
  }, [selectedHeirId]);

  // ── Send handler ────────────────────────────────────────────────────────────
  async function handleSend(e) {
    e.preventDefault();
    const text = replyText.trim();
    if ((!text && !attachmentFile) || !selectedHeirId) return;

    setSending(true);
    setActionError(null);

    try {
      const formData = new FormData();
      if (text) {
        formData.append(openHeirTicket ? 'response' : 'message', text);
      }
      if (attachmentFile) {
        formData.append('file', attachmentFile);
      }

      if (openHeirTicket) {
        // Reply to the heir's unresponded request (marks it RESPONDED)
        const res = await fetch(`/api/help/${openHeirTicket.id}/reply`, {
          method: 'POST',
          credentials: 'same-origin',
          body: formData,
        });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || `Failed to send reply (${res.status})`);
        }
        const updated = await res.json();
        setTickets((current) =>
          current.map((t) => (t.id === updated.id ? updated : t)),
        );
      } else {
        // Send a new direct message to the selected heir
        formData.append('heir_id', selectedHeirId);
        const res = await fetch(`/api/sessions/${sessionId}/help/direct`, {
          method: 'POST',
          credentials: 'same-origin',
          body: formData,
        });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || `Failed to send message (${res.status})`);
        }
        const created = await res.json();
        setTickets((current) => [
          ...current.filter((t) => t.id !== created.id),
          created,
        ]);
      }

      setReplyText('');
      clearAttachment();
      if (textareaRef.current) textareaRef.current.focus();
    } catch (err) {
      setActionError(err.message || 'Failed to send message');
    } finally {
      setSending(false);
    }
  }

  // ── Resolve ticket ──────────────────────────────────────────────────────────
  async function handleResolve(ticketId) {
    if (!ticketId) return;
    setResolving(true);
    setActionError(null);
    try {
      const res = await fetch(`/api/help/${ticketId}/resolve`, {
        method: 'POST',
        credentials: 'same-origin',
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Failed to resolve (${res.status})`);
      }
      const data = await res.json();
      const updated = data.ticket || { ...activeTickets.find((t) => t.id === ticketId), status: 'RESOLVED' };
      setTickets((current) =>
        current.map((t) => (t.id === ticketId ? updated : t)),
      );
    } catch (err) {
      setActionError(err.message || 'Failed to resolve');
    } finally {
      setResolving(false);
    }
  }

  // ── Keyboard shortcut: Enter to send ───────────────────────────────────────
  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend(e);
    }
  }

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <section className="admin-communications-panel" aria-label="Heir communications">
      {/* Header */}
      <div className="communications-header">
        <div>
          <p className="allocation-eyebrow">Executor Communications</p>
          <h3>Heir Message Ledger</h3>
          <p className="text-sm text-muted">
            Full conversation history is preserved for the official estate record.
          </p>
        </div>
        <div className="communications-header-actions">
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={fetchTickets}
            disabled={loading}
          >
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
      </div>

      {error && <div className="banner banner-error">{error}</div>}
      {actionError && <div className="banner banner-error">{actionError}</div>}

      {/* Main layout */}
      <div className={`communications-layout redesigned${isAuditOpen && auditTicket ? '' : ''}`}>

        {/* ── Sidebar: heir thread list ─── */}
        <div className="heir-threads-sidebar">
          <div className="search-box-wrapper" style={{ padding: 'var(--space-sm) 0' }}>
            <input
              type="text"
              className="form-input"
              style={{ fontSize: '0.85rem', padding: '6px 10px' }}
              placeholder="Search heirs…"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          </div>

          <div className="thread-filters">
            {['ALL', 'OPEN', 'RESOLVED'].map((mode) => (
              <button
                key={mode}
                type="button"
                className={`filter-tab ${filterMode === mode ? 'active' : ''}`}
                onClick={() => setFilterMode(mode)}
              >
                {mode === 'ALL' ? 'All' : mode === 'OPEN' ? 'Open' : 'Done'}
              </button>
            ))}
          </div>

          <div className="heir-threads-list" role="tablist" aria-label="Heir threads">
            {filteredConversations.length === 0 ? (
              <p className="text-xs text-muted" style={{ textAlign: 'center', marginTop: 'var(--space-md)' }}>
                No heirs found.
              </p>
            ) : (
              filteredConversations.map(({ heir, openCount, lastMsgText }) => (
                <button
                  key={heir.id}
                  type="button"
                  className={`heir-thread-item ${selectedHeirId === heir.id ? 'active' : ''}`}
                  onClick={() => setSelectedHeirId(heir.id)}
                  role="tab"
                  aria-selected={selectedHeirId === heir.id}
                >
                  <div className="heir-thread-info">
                    <strong>{heirDisplayName(heir)}</strong>
                    {openCount > 0 && (
                      <span className="unresolved-badge">{openCount}</span>
                    )}
                  </div>
                  <small className="last-message-preview">
                    {lastMsgText || 'No messages yet'}
                  </small>
                </button>
              ))
            )}
          </div>
        </div>

        {/* ── Chat stream panel ─── */}
        <div className="chat-stream-container">
          {selectedHeir ? (
            <>
              {/* Header */}
              <div className="chat-stream-header">
                <div>
                  <h4>{heirDisplayName(selectedHeir)}</h4>
                  <p className="text-xs text-muted" style={{ margin: 0 }}>
                    {selectedHeir.email || 'No email registered'}
                  </p>
                </div>
                <div style={{ display: 'flex', gap: 'var(--space-xs)' }}>
                  {openHeirTicket && (
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={() => handleResolve(openHeirTicket.id)}
                      disabled={resolving}
                      title="Mark this heir's open request as resolved"
                    >
                      {resolving ? 'Resolving…' : 'Mark Resolved'}
                    </button>
                  )}
                </div>
              </div>

              {/* Message timeline */}
              <div
                ref={timelineRef}
                className="chat-bubbles-timeline"
                aria-label="Message history"
              >
                {virtualMessages.length === 0 ? (
                  <div className="chat-empty-timeline">
                    <p className="text-sm text-muted">
                      No messages with {heirDisplayName(selectedHeir)}.
                    </p>
                    <p className="text-xs text-muted">
                      Type a message below to start the conversation.
                    </p>
                  </div>
                ) : (
                  virtualMessages.map((msg) => {
                    const isOutgoing = msg.from === 'admin';
                    return (
                      <div
                        key={msg.id}
                        className={`chat-bubble-wrapper ${isOutgoing ? 'outgoing' : 'incoming'}`}
                      >
                        <div className="chat-bubble-content">
                          <div className="chat-bubble-meta">
                            <span className="sender-label">
                              {isOutgoing ? 'You' : heirDisplayName(selectedHeir)}
                            </span>
                            {msg.ticket && !isOutgoing && (
                              <span className={`status-pill ${statusClass(msg.ticket.status)}`}>
                                {msg.ticket.status}
                              </span>
                            )}
                          </div>
                          {msg.imageUri && (
                            <img
                              src={msg.imageUri}
                              alt="Attachment"
                              style={{
                                maxWidth: '100%',
                                borderRadius: '8px',
                                marginTop: '4px',
                                marginBottom: '8px',
                              }}
                            />
                          )}
                          <p className="chat-bubble-text">{msg.text}</p>
                          <div className="chat-bubble-footer">
                            <small>{formatTime(msg.timestamp)}</small>
                            {msg.ticket && !isOutgoing && msg.ticket.status === 'OPEN' && (
                              <button
                                type="button"
                                className="bubble-audit-btn"
                                onClick={() => {
                                  setAuditTicketId(msg.ticketId);
                                  setIsAuditOpen(true);
                                }}
                                title="View audit details"
                              >
                                ⋯
                              </button>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>

              {/* Composer */}
              <form className="chat-reply-composer" onSubmit={handleSend}>
                <div className="composer-reply-target">
                  {openHeirTicket ? (
                    <small>
                      Replying to{' '}
                      <strong>{heirDisplayName(selectedHeir)}</strong>
                      {': '}
                      <em>"{openHeirTicket.message}"</em>
                    </small>
                  ) : (
                    <small>
                      New message to{' '}
                      <strong>{heirDisplayName(selectedHeir)}</strong>
                    </small>
                  )}
                </div>
                {attachmentPreviewUrl && (
                  <div style={{ marginBottom: '8px', position: 'relative', display: 'inline-block' }}>
                    <img
                      src={attachmentPreviewUrl}
                      alt="Preview"
                      style={{ height: '80px', borderRadius: '8px', border: '1px solid var(--color-border)' }}
                    />
                    <button
                      type="button"
                      onClick={clearAttachment}
                      style={{
                        position: 'absolute',
                        top: '-6px',
                        right: '-6px',
                        background: 'red',
                        color: 'white',
                        border: 'none',
                        borderRadius: '50%',
                        width: '20px',
                        height: '20px',
                        cursor: 'pointer',
                        fontSize: '12px',
                        lineHeight: '12px',
                        padding: 0,
                      }}
                    >
                      ×
                    </button>
                  </div>
                )}
                <div className="composer-input-row">
                  <input
                    type="file"
                    accept="image/*"
                    style={{ display: 'none' }}
                    ref={fileInputRef}
                    onChange={handleAttachmentSelect}
                  />
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    style={{ padding: '0 12px', fontSize: '18px' }}
                    onClick={() => fileInputRef.current?.click()}
                    title="Attach Image"
                  >
                    📎
                  </button>
                  <textarea
                    ref={textareaRef}
                    id="executor-reply"
                    className="form-input form-textarea"
                    value={replyText}
                    onChange={(e) => setReplyText(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder={
                      openHeirTicket
                        ? 'Write a reply… (Enter to send, Shift+Enter for newline)'
                        : `Message ${heirDisplayName(selectedHeir)}… (Enter to send)`
                    }
                    maxLength={2000}
                    data-testid="executor-reply-textarea"
                    rows={1}
                  />
                  <button
                    type="submit"
                    className="btn btn-primary btn-sm"
                    disabled={(!replyText.trim() && !attachmentFile) || sending}
                    data-testid="send-executor-reply-btn"
                  >
                    {sending ? '…' : 'Send'}
                  </button>
                </div>
              </form>
            </>
          ) : (
            <div className="chat-stream-empty">
              <h4>Select a conversation</h4>
              <p className="text-sm text-muted">
                Choose a heir from the list on the left to view their message history.
              </p>
            </div>
          )}
        </div>

        {/* ── Legal Audit Drawer (slide-in on demand) ─── */}
        {isAuditOpen && auditTicket && (
          <div className="legal-audit-drawer">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h4>Legal Audit Trail</h4>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => { setIsAuditOpen(false); setAuditTicketId(null); }}
              >
                Close
              </button>
            </div>
            <p className="text-xs text-muted" style={{ marginBottom: 'var(--space-md)' }}>
              All records are cryptographically signed and immutably stored.
            </p>

            <div className="audit-detail-card">
              <div className="audit-section-head">
                <h5>Record Details</h5>
                <span className={`badge ${statusClass(auditTicket.status)}`}>
                  {auditTicket.status}
                </span>
              </div>

              <div className="audit-meta-list">
                <div className="audit-meta-item">
                  <span>Type</span>
                  <strong>{isExecutorMessage(auditTicket) ? 'Executor direct message' : 'Heir request'}</strong>
                </div>
                <div className="audit-meta-item">
                  <span>Communication ID</span>
                  <small className="audit-mono">{auditTicket.id}</small>
                </div>
                <div className="audit-meta-item">
                  <span>Heir ID</span>
                  <small className="audit-mono">{auditTicket.heir_id}</small>
                </div>
                <div className="audit-meta-item">
                  <span>Submitted At</span>
                  <strong>{formatDateTime(auditTicket.created_at)}</strong>
                </div>
                <div className="audit-meta-item">
                  <span>Responded At</span>
                  <strong>{formatDateTime(auditTicket.responded_at)}</strong>
                </div>
                <div className="audit-meta-item">
                  <span>Resolved At</span>
                  <strong>{formatDateTime(auditTicket.resolved_at)}</strong>
                </div>
              </div>

              <div className="audit-actions">
                <button
                  type="button"
                  className="btn btn-secondary btn-sm w-full"
                  onClick={() => handleResolve(auditTicket.id)}
                  disabled={auditTicket.status === 'RESOLVED' || resolving}
                >
                  {resolving ? 'Resolving…' : 'Mark Resolved'}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
