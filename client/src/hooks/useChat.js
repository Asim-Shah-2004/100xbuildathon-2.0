import { useState, useRef, useEffect } from 'react';
import { createNewChat, sendChatMessage, getTables, getChatHistory, sendGlobalChatMessage } from '../services/api';
import { generateTableName } from '../config/constants';
import { toast } from 'sonner';
import posthog from 'posthog-js';

export const useChat = () => {
  const [chats, setChats] = useState([]);
  const [activeChat, setActiveChat] = useState(null);
  const [showNewChatModal, setShowNewChatModal] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [message, setMessage] = useState('');
  const messagesEndRef = useRef(null);

  // New chat form state
  const [roleName, setRoleName] = useState('');
  const [jdFile, setJdFile] = useState(null);
  const [candidatesFile, setCandidatesFile] = useState(null);
  const [mode, setMode] = useState('database'); // 'database' or 'global'

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [activeChat?.messages]);

  // Load existing tables on mount
  useEffect(() => {
    const loadTables = async () => {
      try {
        const tablesData = await getTables();
        if (tablesData && Array.isArray(tablesData.tables)) {
          // Filter out system tables
          const userTables = tablesData.tables.filter(tableName => 
            !['rejected_candidates', 'candidates'].includes(tableName)
          );

          // Convert tables data to chat format
          const existingChats = userTables.map(tableName => {
            // Try to extract timestamp if it exists in the table name
            const parts = tableName.split('_');
            const timestamp = parts[parts.length - 1];
            const roleName = parts.slice(0, -1).join('_'); // Everything before the last underscore
            
            let createdAt;
            if (timestamp && !isNaN(timestamp)) {
              createdAt = new Date(parseInt(timestamp)).toLocaleString();
            } else {
              createdAt = new Date().toLocaleString(); // Fallback for tables without timestamp
            }

            return {
              id: Date.now() + Math.random(), // Generate unique ID
              title: roleName || tableName, // Use role name if available, otherwise use full table name
              roleName: roleName || tableName,
              tableName: tableName,
              messages: [], // Initialize with empty messages
              processed: true,
              createdAt: createdAt
            };
          });
          
          // Sort chats by creation time, newest first
          existingChats.sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
          
          setChats(existingChats);
          
          if (existingChats.length > 0) {
            toast.success(`Loaded ${existingChats.length} existing chats`);
          }
        }
      } catch (error) {
        console.error('Failed to load existing chats:', error);
        toast.error('Failed to load existing chats');
      }
    };

    loadTables();
  }, []);

  const createNewChatSession = async () => {
    if (!roleName || !jdFile || !candidatesFile) return;

    setIsProcessing(true);
    const tableName = generateTableName(roleName);
    posthog.capture("create_new_chat", {
    timestamp: new Date().toISOString(),
    properties: {
      buttonName: 'Create New Chat',   
 },
  });
    
    // Show initial processing toast
    toast.info(`Processing ${candidatesFile.name} for ${roleName} position...`, {
      duration: 3000
    });
    
    try {
      const result = await createNewChat(candidatesFile, jdFile, tableName);
      
      const newChat = {
        id: Date.now(),
        title: roleName,
        roleName,
        tableName,
        jdFileName: jdFile.name,
        candidatesFileName: candidatesFile.name,
        messages: [{
          id: Date.now(),
          type: 'system',
          content: result.message,
          timestamp: new Date().toLocaleTimeString()
        }],
        processed: true,
        createdAt: new Date().toLocaleString()
      };
      
      setChats(prev => [newChat, ...prev]);
      setActiveChat(newChat);
      setShowNewChatModal(false);
      
      // Show success toast with more details
      toast.success(`Successfully processed ${candidatesFile.name} for ${roleName} position. Ready to analyze!`, {
        duration: 4000
      });
    } catch (error) {
      console.error('Failed to create new chat:', error);
      toast.error(`Failed to process ${candidatesFile.name}. Please try again.`, {
        duration: 4000
      });
    } finally {
      setIsProcessing(false);
      setRoleName('');
      setJdFile(null);
      setCandidatesFile(null);
    }
  };

  const sendMessage = async (messageText) => {
    if (!messageText.trim() || !activeChat || !activeChat.processed) return;

    const userMessage = {
        id: Date.now(),
        type: 'user',
        content: messageText,
        timestamp: new Date().toLocaleTimeString()
    };

    const loadingMessage = {
        id: Date.now() + 1,
        type: 'ai',
        content: '',
        isLoading: true,
        timestamp: new Date().toLocaleTimeString()
    };

    const updatedChat = {
        ...activeChat,
        messages: [...activeChat.messages, userMessage, loadingMessage]
    };

    setChats(prev => prev.map(chat => 
        chat.id === activeChat.id ? updatedChat : chat
    ));
    setActiveChat(updatedChat);

    try {
      let aiMessage;
      if (mode === 'global') {
        // Use /chat/2 endpoint
        const response = await sendGlobalChatMessage(messageText);
        aiMessage = {
          id: loadingMessage.id,
          type: 'ai',
          content: response,
          isLoading: false,
          timestamp: new Date().toLocaleTimeString()
        };
      } else {
        // Use /chat endpoint (database mode)
        const response = await sendChatMessage(activeChat.tableName, messageText);
        aiMessage = {
          id: loadingMessage.id,
          type: 'ai',
          content: response.result,
          followups: response.followups,
          isLoading: false,
          timestamp: new Date().toLocaleTimeString()
        };
      }

      const finalChat = {
        ...updatedChat,
        messages: [...updatedChat.messages.slice(0, -1), aiMessage]
      };

      setChats(prev => prev.map(chat => 
        chat.id === activeChat.id ? finalChat : chat
      ));
      setActiveChat(finalChat);
      return aiMessage.followups;
    } catch (error) {
      console.error('Failed to get response:', error);
      // Remove loading message on error
      const finalChat = {
        ...updatedChat,
        messages: updatedChat.messages.slice(0, -1)
      };
      setChats(prev => prev.map(chat => 
        chat.id === activeChat.id ? finalChat : chat
      ));
    }
  };

  // Fetch chat history when activeChat changes
  useEffect(() => {
    const fetchHistory = async () => {
      if (activeChat && activeChat.tableName && localStorage.getItem('user_id')) {
        try {
          const chatsArr = await getChatHistory(localStorage.getItem('user_id'), activeChat.tableName);
          // chatsArr is an array of [question, answer] pairs
          const messages = [];
          chatsArr.forEach(([question, answer], idx) => {
            messages.push({
              id: `${activeChat.tableName}-q-${idx}`,
              type: 'user',
              content: question,
              timestamp: ''
            });
            messages.push({
              id: `${activeChat.tableName}-a-${idx}`,
              type: 'ai',
              content: answer,
              timestamp: ''
            });
          });
          setChats(prev => prev.map(chat =>
            chat.tableName === activeChat.tableName ? { ...chat, messages } : chat
          ));
          setActiveChat(prev => prev ? { ...prev, messages } : prev);
        } catch (e) {
          // Optionally handle error
        }
      }
    };
    fetchHistory();
    // eslint-disable-next-line
  }, [activeChat && activeChat.tableName]);

  return {
    chats,
    activeChat,
    showNewChatModal,
    isProcessing,
    message,
    roleName,
    jdFile,
    candidatesFile,
    messagesEndRef,
    setActiveChat,
    setShowNewChatModal,
    setMessage,
    setRoleName,
    setJdFile,
    setCandidatesFile,
    createNewChat: createNewChatSession,
    sendMessage,
    mode,
    setMode
  };
};

export default useChat; 