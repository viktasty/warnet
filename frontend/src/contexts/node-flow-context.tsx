import React, { useState, useEffect } from "react";
import { CANVAS_HEIGHT, CANVAS_WIDTH } from "@/config";
import {
  GraphEdge,
  GraphNode,
  NetworkTopology,
  NodeGraphContext,
  NodePersona,
  NodePersonaType,
} from "@/flowTypes";
import { defaultNodePersona } from "@/app/data";
import { v4 } from 'uuid';
import { Edge, Node, useEdgesState, useNodesState } from "reactflow";
export const nodeFlowContext = React.createContext<NodeGraphContext>(null!);

export const NodeGraphFlowProvider = ({
  children,
}: {
  children: React.ReactNode;
}) => {
  const [isDialogOpen, setIsDialogOpen] = useState<boolean>(false);
  const [showGraph, setShowGraph] = useState<boolean>(false);
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [nodePersonaType, setNodePersonaType] =
    useState<NodePersonaType | null>(null);
  const [nodePersona, setNodePersona] = useState<NodePersona | null>(
    defaultNodePersona
  );
  const [nodeInfo, setNodeInfo] = useState<Node<Partial<GraphNode>> | null>(null)
  const openDialog = () => setIsDialogOpen(true);
  const closeDialog = () => {
    setIsDialogOpen(false);
    setNodeInfo(null)
    // setSteps(-1);
  };

  const setNodePersonaFunc = ({type, nodePersona}: NetworkTopology) => {
    setNodePersonaType(type)
    setNodePersona(nodePersona)
    setNodes(nodePersona.nodes)
    setNodeEdges(nodePersona.edges)
  };

  const showGraphFunc = () => {
    // setSteps(2);
    setShowGraph(true);
  };

  // const setStep = (step: Steps) => {
  //   setSteps(step);
  // };

  const showNodePersonaInfo = () => {
    // setSteps(1);
  };

  const setNodeEdges = (edge: Edge<Partial<GraphEdge>>[]) => {
    setEdges([...edge]);
  };

  const generateNodeGraph = () => {
    // const nodeGraph = {
    //   nodes: nodes,
    //   edges: edges,
    // };
    // generateGraphML({ nodes, edges });
  };

  const createNewNode = () => {
    const newNodesNumber = nodes.filter(node => node.data?.label.includes("new node")).length
    const id =(nodes[nodes.length -1]!.id ?? 0) + 1
    const newNode: Node<Partial<GraphNode>> =
      {
        id,
        data:{
            label:"new node " + newNodesNumber,
            name:"new node " + newNodesNumber,
        },
        type:"draggable",
        position: {
        x: CANVAS_WIDTH / 2,
        y: CANVAS_HEIGHT / 2,
        }
      }
    return newNode;
  }

  const addNode = (node?: Node<Partial<GraphNode>>) => {
    const newNode = node ? node : createNewNode()
    setNodes([...nodes, newNode]);
    setNodeInfo(newNode)
    openDialog()
  };

  const editNode = (node: Node<Partial<GraphNode>>) => {
    setNodeInfo(node)
    openDialog()
  }
  
  const duplicateNode = (node: Node<Partial<GraphNode>>) => {
    const length = nodes.length
    const duplicateNode = {...node, id:`${length}`,data:{label:`${node?.data?.label} duplicate`, name:`${node?.data?.label} duplicate`}}
    addNode(duplicateNode)
  }

  const updateNodeInfo = (nodeProperty: any, value: any) => {
    if (!nodeInfo) return
    const duplNode = {...nodeInfo}
    //@ts-ignore partia will come back to it
    duplNode.data[nodeProperty]  = value
    setNodeInfo(duplNode)
  }

  const saveEditedNode = () => {
    if (!nodeInfo) return;
    const nodeIndex = nodes.findIndex((node) => node.id === nodeInfo?.id)
    if (nodeIndex !== -1) {
      const newList = [...nodes]
      const newEdges = [...edges]
      newList[nodeIndex] = nodeInfo
      const strippedEdges = newEdges.map(({source, target, id}) => ({id,source: source, target: target}))
      setNodes(newList)
      setEdges(strippedEdges)
      closeDialog()
    }
  }

  const deleteNode = (node: Node<Partial<GraphNode>>) => {
    const updatedNodes = nodes.filter(({ id }) => id !== node.id)
    const newEdges = edges.filter(({source, target}) => {
      // remove edge if source or target is linked to the node
      return !(source === node.id || target === node.id)
    })
    setEdges(newEdges)
    setNodes(updatedNodes)
  }

  function stripEdges(edges: GraphEdge[]) {
    return edges.map(({source, target}) => ({source: source.id, target: target.id}))
  }

  // React.useEffect(() => {
  //   console.log("nodes", nodes);
  //   console.log("edges", edges);
  // }, [nodes, edges]);

  return (
    <nodeFlowContext.Provider
      value={{
        nodes,
        edges,
        setEdges,
        setNodes,
        nodePersona,
        nodePersonaType,
        isDialogOpen,
        showGraph,
        nodeInfo,
        updateNodeInfo,
        editNode,
        saveEditedNode,
        // setNodeInfo,
        showGraphFunc,
        openDialog,
        closeDialog,
        addNode,
        duplicateNode,
        deleteNode,
        setNodePersonaFunc,
        showNodePersonaInfo,
        setNodeEdges,
        generateNodeGraph,
        onNodesChange,
        onEdgesChange
      }}
    >
      {children}
    </nodeFlowContext.Provider>
  );
};

export const useNodeFlowContext = () => {
  const context = React.useContext(nodeFlowContext);
  if (context === undefined) {
    throw new Error(
      "useNodeGraphContext must be used within a NodeGraphProvider"
    );
  }
  return context;
};
