// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import BIP39MnemonicScreen from './BIP39MnemonicScreen';
import '@testing-library/jest-dom';

describe('BIP39MnemonicScreen Component', () => {
  const sampleWords = [
    'abandon', 'ability', 'able', 'about', 'above', 'absent',
    'absorb', 'abstract', 'absurd', 'abuse', 'access', 'accident',
    'account', 'accuse', 'achieve', 'acid', 'acoustic', 'acquire',
    'across', 'act', 'action', 'actor', 'actress', 'actual',
  ];

  it('renders the admin setup title', () => {
    render(<BIP39MnemonicScreen mnemonicWords={[]} />);
    expect(
      screen.getByText('Administrative Setup & Recovery Key'),
    ).toBeInTheDocument();
  });

  it('renders all 24 words in the grid with indices', () => {
    render(<BIP39MnemonicScreen mnemonicWords={sampleWords} />);

    for (let i = 0; i < 24; i++) {
      const el = screen.getByTestId(`mnemonic-word-${i}`);
      expect(el).toBeInTheDocument();
      expect(el.textContent).toContain(sampleWords[i]);
    }
  });

  it('renders the mnemonic grid with dashed border styling', () => {
    render(<BIP39MnemonicScreen mnemonicWords={sampleWords} />);
    const grid = screen.getByTestId('mnemonic-grid');
    expect(grid).toBeInTheDocument();
  });

  it('displays the warning banner with key text', () => {
    render(<BIP39MnemonicScreen mnemonicWords={sampleWords} />);
    const warning = screen.getByTestId('mnemonic-warning');
    expect(warning).toBeInTheDocument();
    expect(warning.textContent).toContain(
      'WARNING: Store this key offline in a secure physical location',
    );
    expect(warning.textContent).toContain('ONLY');
    expect(warning.textContent).toContain(
      'If lost, your backups are permanently unrecoverable',
    );
  });

  it('disables the proceed button when checkbox is not checked', () => {
    render(<BIP39MnemonicScreen mnemonicWords={sampleWords} />);
    const btn = screen.getByTestId('mnemonic-proceed-btn');
    expect(btn).toBeDisabled();
  });

  it('enables the proceed button when checkbox is checked', () => {
    render(<BIP39MnemonicScreen mnemonicWords={sampleWords} />);
    const checkbox = screen.getByTestId('mnemonic-confirm-checkbox');

    fireEvent.click(checkbox);

    const btn = screen.getByTestId('mnemonic-proceed-btn');
    expect(btn).not.toBeDisabled();
  });

  it('calls onConfirmed when proceed is clicked after confirmation', () => {
    const onConfirmed = vi.fn();
    render(
      <BIP39MnemonicScreen
        mnemonicWords={sampleWords}
        onConfirmed={onConfirmed}
      />,
    );

    const checkbox = screen.getByTestId('mnemonic-confirm-checkbox');
    fireEvent.click(checkbox);

    const btn = screen.getByTestId('mnemonic-proceed-btn');
    fireEvent.click(btn);

    expect(onConfirmed).toHaveBeenCalledTimes(1);
  });

  it('does not call onConfirmed when proceed is clicked without confirmation', () => {
    const onConfirmed = vi.fn();
    render(
      <BIP39MnemonicScreen
        mnemonicWords={sampleWords}
        onConfirmed={onConfirmed}
      />,
    );

    const btn = screen.getByTestId('mnemonic-proceed-btn');
    // Button is disabled so click won't fire onClick
    expect(btn).toBeDisabled();
    expect(onConfirmed).not.toHaveBeenCalled();
  });

  it('handles empty word array gracefully', () => {
    render(<BIP39MnemonicScreen mnemonicWords={[]} />);
    const grid = screen.getByTestId('mnemonic-grid');
    expect(grid).toBeInTheDocument();
    // No word elements rendered
    expect(screen.queryByTestId('mnemonic-word-0')).not.toBeInTheDocument();
  });

  it('renders confirmation label text correctly', () => {
    render(<BIP39MnemonicScreen mnemonicWords={sampleWords} />);
    expect(
      screen.getByText(/I have copied and verified my 24-word Paper Recovery Key/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/understand it cannot be recovered if lost/),
    ).toBeInTheDocument();
  });
});