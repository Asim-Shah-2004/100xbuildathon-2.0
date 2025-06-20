import { BACKEND_URL } from '../config/constants';

// Common headers and request options
const commonHeaders = {
    'ngrok-skip-browser-warning': 'true',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
};

const commonOptions = {
    mode: 'cors',
    credentials: 'omit', // Changed from 'include' to 'omit' to avoid CORS issues
};

export const createNewChat = async (candidatesFile, jdFile, tableName) => {
    try {
        const formData = new FormData();
        formData.append('csv', candidatesFile);
        formData.append('pdf', jdFile);
        formData.append('tableName', tableName);

        const response = await fetch(`${BACKEND_URL}/newChat`, {
            method: 'POST',
            headers: {
                ...commonHeaders,
            },
            body: formData,
            ...commonOptions,
        });

        if (!response.ok) {
            throw new Error('Failed to create new chat');
        }

        const data = await response.json();
        return data.result;
    } catch (error) {
        console.error('Error creating new chat:', error);
        throw error;
    }
};

export const sendChatMessage = async (tableName, query) => {
    try {
        const response = await fetch(`${BACKEND_URL}/chat`, {
            method: 'POST',
            headers: {
                ...commonHeaders,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ tableName, query, user_id: localStorage.getItem('user_id') }),
            ...commonOptions,
        });
        if (!response.ok) {
            throw new Error('Failed to send message');
        }
        const data = await response.json();
        // data.result (string), data.followups (array)
        return data;
    } catch (error) {
        console.error('Error sending message:', error);
        throw error;
    }
};

export const getTables = async () => {
    try {
        const response = await fetch(`${BACKEND_URL}/gettables`, {
            method: 'GET',
            headers: {
                ...commonHeaders,
                'Content-Type': 'application/json',
            },
            ...commonOptions,
        });
        
        if (!response.ok) {
            throw new Error('Failed to get tables');
        }

        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Error getting tables:', error);
        throw error;
    }
};

export const registerUser = async (company_name, user_id, password) => {
    try {
        const response = await fetch(`${BACKEND_URL}/register`, {
            method: 'POST',
            headers: {
                ...commonHeaders,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ company_name, user_id, password }),
            ...commonOptions,
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'Registration failed');
        }
        return data;
    } catch (error) {
        throw error;
    }
};

export const loginUser = async (user_id, password) => {
    try {
        const response = await fetch(`${BACKEND_URL}/login`, {
            method: 'POST',
            headers: {
                ...commonHeaders,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ user_id, password }),
            ...commonOptions,
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'Login failed');
        }
        return data;
    } catch (error) {
        throw error;
    }
};

export const getChatHistory = async (user_id, tableName) => {
    try {
        const response = await fetch(`${BACKEND_URL}/get-chats?user_id=${encodeURIComponent(user_id)}&tableName=${encodeURIComponent(tableName)}`, {
            method: 'GET',
            headers: {
                ...commonHeaders,
                'Content-Type': 'application/json',
            },
            ...commonOptions,
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'Failed to fetch chat history');
        }
        return data.chats;
    } catch (error) {
        throw error;
    }
};

export const sendGlobalChatMessage = async (prompt) => {
    try {
        const response = await fetch(`${BACKEND_URL}/chat/2`, {
            method: 'POST',
            headers: {
                ...commonHeaders,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ prompt }),
            ...commonOptions,
        });
        if (!response.ok) {
            throw new Error('Failed to send global message');
        }
        const data = await response.json();
        // data.response (string)
        return data.response;
    } catch (error) {
        console.error('Error sending global message:', error);
        throw error;
    }
}; 