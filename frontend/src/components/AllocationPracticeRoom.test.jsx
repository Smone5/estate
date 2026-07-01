// @vitest-environment jsdom
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import '@testing-library/jest-dom';
import AllocationPracticeRoom, { simulateFullAllocation } from './AllocationPracticeRoom';
import { DEFAULT_SIMULATION_CONFIG } from '../utils/simulationConfig';

function renderRoom() {
  return render(
    <MemoryRouter>
      <AllocationPracticeRoom />
    </MemoryRouter>,
  );
}

describe('simulateFullAllocation', () => {
  it('checks every complete three-person assignment and assigns every item once', () => {
    const items = DEFAULT_SIMULATION_CONFIG.items;
    const valuations = {
      you: Object.fromEntries(items.map((item, index) => [item.id, [310, 210, 170, 130, 110, 70][index]])),
      jordan: Object.fromEntries(items.map((item) => [item.id, item.companion_points.jordan])),
      casey: Object.fromEntries(items.map((item) => [item.id, item.companion_points.casey])),
    };

    const result = simulateFullAllocation(items, valuations);

    expect(result.assignmentsToCheck).toBe(729);
    expect(Object.keys(result.assignment)).toHaveLength(6);
    expect(result.product).toBe(result.utility.you * result.utility.jordan * result.utility.casey);
  });
});

describe('AllocationPracticeRoom journey', () => {
  beforeEach(() => {
    window.scrollTo = vi.fn();
    global.fetch = vi.fn().mockRejectedValue(new Error('offline'));
  });

  it('moves from orientation into a six-item photo catalog', async () => {
    renderRoom();

    fireEvent.click(await screen.findByRole('button', { name: /Enter the practice estate/i }));

    expect(await screen.findByRole('heading', { name: /Take your time with the items/i })).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: /Walnut Mantel Clock|Handwritten Recipe Box|35mm Family Camera|Pearl Necklace|Oak Rocking Chair|Harbor Watercolor/i })).toHaveLength(6);
  });

  it('gates review until exactly 1,000 points are allocated', async () => {
    renderRoom();
    fireEvent.click(await screen.findByRole('button', { name: /Enter the practice estate/i }));
    fireEvent.click(await screen.findByRole('button', { name: /Continue to point allocation/i }));

    const reviewButton = screen.getByRole('button', { name: /Review my practice choices/i });
    expect(reviewButton).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: /Fill a sample distribution/i }));

    expect(reviewButton).not.toBeDisabled();
  });

  it('rehearses review, submission, waiting, and the final result', async () => {
    renderRoom();
    fireEvent.click(await screen.findByRole('button', { name: /Enter the practice estate/i }));
    fireEvent.click(await screen.findByRole('button', { name: /Continue to point allocation/i }));
    fireEvent.click(screen.getByRole('button', { name: /Fill a sample distribution/i }));
    fireEvent.click(screen.getByRole('button', { name: /Review my practice choices/i }));

    const submit = screen.getByRole('button', { name: /Submit practice allocation/i });
    expect(submit).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox'));
    expect(submit).not.toBeDisabled();
    fireEvent.click(submit);

    expect(screen.getByRole('heading', { name: /Your choices are safely submitted/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /run allocation/i }));

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /See the whole distribution/i })).toBeInTheDocument();
    });
    expect(screen.getByText(/729 complete distributions/i)).toBeInTheDocument();
    expect(screen.getByText(/You have now experienced the complete process/i)).toBeInTheDocument();
  });

  it('requires confirmation before restarting active work', async () => {
    renderRoom();
    fireEvent.click(await screen.findByRole('button', { name: /Enter the practice estate/i }));

    fireEvent.click(screen.getByRole('button', { name: /Restart simulation/i }));
    expect(screen.getByRole('button', { name: /Confirm restart/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Confirm restart/i }));

    expect(screen.getByRole('heading', { name: /Practice once/i })).toBeInTheDocument();
  });

  it('records completion for the currently registered heir', async () => {
    global.fetch = vi.fn((url) => {
      if (String(url).endsWith('/api/heirs/me/simulation')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            config: DEFAULT_SIMULATION_CONFIG,
            registered: true,
            published: true,
            session_id: 'session-1',
            session_title: 'Smith Estate',
            required_for_launch: true,
            completed_at: null,
          }),
        });
      }
      if (String(url).endsWith('/api/heirs/me/simulation/complete')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ status: 'completed', completed_at: '2026-07-01T12:00:00Z' }),
        });
      }
      if (String(url).endsWith('/api/heirs/me/simulation/solve')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            engine: 'production',
            assignment: {
              'mantel-clock': 'you',
              'recipe-box': 'casey',
              'film-camera': 'jordan',
              'pearl-necklace': 'casey',
              'rocking-chair': 'jordan',
              'harbor-watercolor': 'you',
            },
            utility: { you: 380, jordan: 520, casey: 680 },
            product: 134368000,
            tieEvents: [],
            valuations: {
              you: { 'mantel-clock': 310, 'recipe-box': 210, 'film-camera': 170, 'pearl-necklace': 130, 'rocking-chair': 110, 'harbor-watercolor': 70 },
              jordan: Object.fromEntries(DEFAULT_SIMULATION_CONFIG.items.map((item) => [item.id, item.companion_points.jordan])),
              casey: Object.fromEntries(DEFAULT_SIMULATION_CONFIG.items.map((item) => [item.id, item.companion_points.casey])),
            },
          }),
        });
      }
      return Promise.reject(new Error('Unexpected request'));
    });

    renderRoom();
    expect(await screen.findByText('Registered heir practice step')).toBeInTheDocument();
    expect(screen.getByText('Smith Estate')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Enter the practice estate/i }));
    fireEvent.click(screen.getByRole('button', { name: /Continue to point allocation/i }));
    fireEvent.click(screen.getByRole('button', { name: /Fill a sample distribution/i }));
    fireEvent.click(screen.getByRole('button', { name: /Review my practice choices/i }));
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: /Submit practice allocation/i }));
    fireEvent.click(screen.getByRole('button', { name: /run allocation/i }));

    expect(await screen.findByText(/Practice completion recorded for this estate/i)).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledWith(
      '/api/heirs/me/simulation/complete',
      expect.objectContaining({ method: 'POST' }),
    );
  });
});
