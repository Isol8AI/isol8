import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Sidebar } from '@/components/chat/Sidebar';

const mockSessions = [
  { id: 'session-1', name: 'First Conversation' },
  { id: 'session-2', name: 'Second Conversation' },
  { id: 'session-3', name: 'Third Conversation' },
];

describe('Sidebar', () => {
  const mockOnNewChat = vi.fn();
  const mockOnSelectSession = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('rendering', () => {
    it('renders New Chat button', () => {
      render(<Sidebar />);
      expect(screen.getByText('New Chat')).toBeInTheDocument();
    });

    it('renders session list', () => {
      render(<Sidebar sessions={mockSessions} />);

      for (const session of mockSessions) {
        expect(screen.getByText(session.name)).toBeInTheDocument();
      }
    });

    it('shows empty state when no sessions', () => {
      render(<Sidebar sessions={[]} />);
      expect(screen.getByText('No conversations yet')).toBeInTheDocument();
    });

    it('shows empty state when sessions not provided', () => {
      render(<Sidebar />);
      expect(screen.getByText('No conversations yet')).toBeInTheDocument();
    });

    it('renders version footer', () => {
      render(<Sidebar />);
      expect(screen.getByText('Isol8 v0.1')).toBeInTheDocument();
    });

    it('applies custom className', () => {
      const { container } = render(<Sidebar className="custom-class" />);
      expect(container.firstChild).toHaveClass('custom-class');
    });
  });

  describe('session selection', () => {
    it('calls onNewChat when New Chat button clicked', async () => {
      const user = userEvent.setup();
      render(<Sidebar onNewChat={mockOnNewChat} />);

      await user.click(screen.getByText('New Chat'));

      expect(mockOnNewChat).toHaveBeenCalledTimes(1);
    });

    it('calls onSelectSession with session id when clicked', async () => {
      const user = userEvent.setup();
      render(
        <Sidebar sessions={mockSessions} onSelectSession={mockOnSelectSession} />
      );

      await user.click(screen.getByText('Second Conversation'));

      expect(mockOnSelectSession).toHaveBeenCalledWith('session-2');
    });

    it('handles click when onSelectSession not provided', async () => {
      const user = userEvent.setup();
      render(<Sidebar sessions={mockSessions} />);

      await user.click(screen.getByText('First Conversation'));
    });
  });

  describe('current session highlighting', () => {
    it('highlights current session', () => {
      render(<Sidebar sessions={mockSessions} currentSessionId="session-2" />);

      const currentButton = screen.getByText('Second Conversation').closest('button');
      expect(currentButton).toHaveClass('bg-accent');
    });

    it('does not highlight non-current sessions', () => {
      render(<Sidebar sessions={mockSessions} currentSessionId="session-2" />);

      const otherButton = screen.getByText('First Conversation').closest('button');
      expect(otherButton).not.toHaveClass('bg-accent');
    });
  });
});
