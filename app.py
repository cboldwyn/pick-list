import streamlit as st
import pandas as pd
import numpy as np
from reportlab.lib.pagesizes import letter, A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
import io
from io import StringIO
from datetime import datetime

# Set page config
st.set_page_config(
    page_title="Sales Order Pick List Generator",
    page_icon="📦",
    layout="wide"
)

st.title("📦 Sales Order Pick List Generator")
st.markdown("Generate custom pick lists from your sales order and assembly data with input package tracking")

# Initialize session state
if 'processed_data' not in st.session_state:
    st.session_state.processed_data = None
if 'so_data' not in st.session_state:
    st.session_state.so_data = None
if 'assembly_data' not in st.session_state:
    st.session_state.assembly_data = None

# Function to clean and load CSV data
def load_csv_with_metadata_skip(uploaded_file):
    """
    Load CSV file and skip metadata lines at the top
    """
    try:
        # Read the raw content
        content = uploaded_file.getvalue().decode('utf-8')
        lines = content.split('\n')
        
        # Skip the first 3 lines (metadata) and rejoin
        csv_content = '\n'.join(lines[3:])
        
        # Use StringIO to create a file-like object for pandas
        from io import StringIO
        csv_file = StringIO(csv_content)
        
        # Read with pandas
        df = pd.read_csv(csv_file)
        return df
        
    except Exception as e:
        st.error(f"Error loading CSV: {str(e)}")
        return None

# Function to process the data (replicating your Google Sheets formula)
def process_data(so_df, assembly_df):
    """
    Replicates the Google Sheets QUERY formula logic based on actual CSV structure
    """
    try:
        # Extract relevant columns from Sales Orders using actual column names
        so_columns = {
            'Customer': so_df['Customer'],
            'Order_Number': so_df['Order Number'],
            'Category': so_df['Category'],
            'Product': so_df['Product'],
            'Batch_Number': so_df['Package Batch Number'],
            'Lookup_Value': so_df['Package Label'],  # This is what we lookup in Assembly
            'Quantity': so_df['Quantity']
        }
        
        # Create base dataframe
        result_df = pd.DataFrame(so_columns)
        
        # Assembly data processing (replicating your VLOOKUP logic)
        # Filter assembly data where Input/Output = "Output"
        assembly_output = assembly_df[assembly_df['Input/Output'] == "Output"]
        assembly_input = assembly_df[assembly_df['Input/Output'] == "Input"]
        
        # Create lookup dictionaries for the nested lookup
        # First lookup: Package Label -> Assembly Number (from Output records)
        package_to_assembly = dict(zip(assembly_output['Package Number'], assembly_output['Assembly Number']))
        
        # Second lookup: Assembly Number -> Package Number (from Input records)  
        assembly_to_input_package = dict(zip(assembly_input['Assembly Number'], assembly_input['Package Number']))
        
        # Perform the nested lookup (replicating your VLOOKUP formula)
        input_package_numbers = []
        for lookup_val in result_df['Lookup_Value']:
            try:
                # First lookup: find Assembly Number from Package Label where Input/Output="Output"
                assembly_number = package_to_assembly.get(lookup_val, None)
                # Second lookup: find Package Number from Assembly Number where Input/Output="Input"
                input_package = assembly_to_input_package.get(assembly_number, "") if assembly_number else ""
                input_package_numbers.append(input_package)
            except:
                input_package_numbers.append("")
        
        result_df['Input_Package_Number'] = input_package_numbers
        
        # Remove the Lookup_Value column as it's not needed in the final output
        result_df = result_df.drop('Lookup_Value', axis=1)
        
        # Reorder columns to put Quantity last
        columns_order = ['Customer', 'Order_Number', 'Category', 'Product', 'Batch_Number', 'Input_Package_Number', 'Quantity']
        result_df = result_df[columns_order]
        
        # Filter out null customers and sort (replicating your QUERY)
        result_df = result_df[result_df['Customer'].notna() & (result_df['Customer'] != "")]
        result_df = result_df.sort_values(['Customer', 'Order_Number', 'Category', 'Product'])
        
        # Reset index
        result_df = result_df.reset_index(drop=True)
        
        return result_df
        
    except Exception as e:
        st.error(f"Error processing data: {str(e)}")
        st.info("Please check that your CSV files have the expected column structure.")
        st.info(f"Available Sales Order columns: {list(so_df.columns)}")
        st.info(f"Available Assembly columns: {list(assembly_df.columns)}")
        return None

# Function to generate PDF
def generate_pdf(df, selected_filters=None):
    """
    Generate a styled PDF report with landscape orientation and professional colors
    """
    buffer = io.BytesIO()
    
    # Use landscape orientation
    from reportlab.lib.pagesizes import landscape, A4
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), 
                          topMargin=0.5*inch, bottomMargin=0.75*inch,
                          leftMargin=0.5*inch, rightMargin=0.5*inch)
    
    # Get styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.Color(0.2, 0.4, 0.2),  # Dark green
        alignment=1,  # Center alignment
        spaceAfter=10
    )
    
    elements = []
    
    # Compact title
    title = Paragraph("Sales Order Pick List", title_style)
    elements.append(title)
    
    # Add filter information if any (compact)
    if selected_filters:
        filter_parts = []
        for key, value in selected_filters.items():
            if value:
                filter_parts.append(f"{key}: {', '.join(value) if isinstance(value, list) else value}")
        if filter_parts:
            filter_text = " | ".join(filter_parts)
            filter_para = Paragraph(f"<i>{filter_text}</i>", styles['Normal'])
            elements.append(filter_para)
            elements.append(Spacer(1, 10))
    
    # Function to wrap text for display
    def wrap_text(text, max_length=20, break_chars=['-', ' ']):
        """Simple text wrapping function"""
        if not text or len(str(text)) <= max_length:
            return str(text)
        
        text = str(text)
        
        # Find break points
        for i in range(min(max_length, len(text)), 0, -1):
            if text[i-1] in break_chars:
                return text[:i-1] + '\n' + text[i:]
        
        # No good break point found, break at max_length
        return text[:max_length] + '\n' + text[max_length:]
    
    # Function to get last 14 characters of package number
    def truncate_package_number(package_text):
        if not package_text or len(str(package_text)) <= 14:
            return str(package_text)
        return str(package_text)[-14:]
    
    # Prepare table data with Picked column
    headers = ['Customer', 'Order Number', 'Category', 'Product', 'Batch Number', 'Input Package Number', 'Quantity', 'Picked']
    table_data = [headers]
    
    for _, row in df.iterrows():
        # Handle None/NaN values for batch number
        batch_number = str(row['Batch_Number']) if pd.notna(row['Batch_Number']) and str(row['Batch_Number']).lower() != 'none' else ""
        
        # Process text fields
        product_name = wrap_text(str(row['Product']), 25)
        batch_display = wrap_text(batch_number, 15, ['-', ' ']) if batch_number else ""
        package_display = truncate_package_number(row['Input_Package_Number']) if pd.notna(row['Input_Package_Number']) else ""
        
        table_data.append([
            str(row['Customer']),
            str(row['Order_Number']),
            str(row['Category']),
            product_name,
            batch_display,
            package_display,
            str(row['Quantity']),
            ""  # Empty Picked column for manual entry
        ])
    
    # Create table with adjusted column widths for landscape
    col_widths = [1.2*inch, 1*inch, 0.8*inch, 2.2*inch, 1*inch, 1*inch, 0.6*inch, 0.8*inch]
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    
    # Professional colors
    header_color = colors.Color(0.25, 0.45, 0.25)  # Dark green
    alt_row_color = colors.Color(0.95, 0.97, 0.95)  # Very light green
    border_color = colors.Color(0.4, 0.6, 0.4)     # Medium green
    
    # Create alternating row styles
    table_style = [
        # Header row
        ('BACKGROUND', (0, 0), (-1, 0), header_color),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        
        # Data rows
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 7),
        ('GRID', (0, 0), (-1, -1), 0.5, border_color),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),  # Changed to TOP for wrapped text
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, alt_row_color]),
    ]
    
    table.setStyle(TableStyle(table_style))
    elements.append(table)
    
    # Simple footer function
    def add_page_footer(canvas, doc):
        """Add footer with page numbers and generation info"""
        canvas.saveState()
        
        # Page number (simple approach)
        page_num = canvas.getPageNumber()
        page_text = f"Page {page_num}"
        
        # Generation info
        gen_time = datetime.now().strftime('%m/%d/%Y %I:%M %p')
        gen_text = f"Generated: {gen_time}"
        
        # Draw footer text
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.Color(0.4, 0.4, 0.4))
        
        # Left side - generation time
        canvas.drawString(0.5*inch, 0.3*inch, gen_text)
        
        # Right side - page number
        canvas.drawRightString(landscape(A4)[0] - 0.5*inch, 0.3*inch, page_text)
        
        canvas.restoreState()
    
    # Build PDF with simple footer (no total page count for now)
    doc.build(elements, onFirstPage=add_page_footer, onLaterPages=add_page_footer)
    buffer.seek(0)
    return buffer

# Sidebar for file uploads
st.sidebar.header("📊 Data Sources")

# Sales Order Item History CSV Upload
st.sidebar.subheader("📋 Sales Order Item History")
st.sidebar.markdown("**All Sales Orders with a status of Processing and an order date within the past 30 days**")
so_file = st.sidebar.file_uploader(
    "Upload Sales Order Item History CSV:",
    type=['csv'],
    key="so_upload",
    help="Upload your sales order CSV with processing orders from the last 30 days. The tool will automatically handle metadata lines and column mapping."
)

# Assembly Data CSV Upload  
st.sidebar.subheader("🔧 Assembly Data")
st.sidebar.markdown("**Assemblies from the Last 3 Days**")
assembly_file = st.sidebar.file_uploader(
    "Upload Assembly Data CSV:",
    type=['csv'],
    key="assembly_upload",
    help="Upload your assembly data CSV containing input/output package relationships from the last 3 days."
)

# Process button
if st.sidebar.button("🚀 Process Data", type="primary", disabled=not (so_file and assembly_file)):
    with st.spinner("Processing your data..."):
        try:
            # Load the data using our custom function that skips metadata
            so_df = load_csv_with_metadata_skip(so_file)
            assembly_df = load_csv_with_metadata_skip(assembly_file)
            
            if so_df is None or assembly_df is None:
                st.error("❌ Failed to load one or both CSV files. Please check your file formats.")
                st.stop()
            
            st.session_state.so_data = so_df
            st.session_state.assembly_data = assembly_df
            
            st.success(f"✅ Files loaded successfully!")
            st.info(f"Sales Orders: {len(so_df):,} rows | Assembly Data: {len(assembly_df):,} rows")
            
            # Process the data
            processed_df = process_data(so_df, assembly_df)
            
            if processed_df is not None:
                st.session_state.processed_data = processed_df
                st.success(f"✅ Successfully processed {len(processed_df):,} records")
            else:
                st.error("❌ Failed to process data. Please check your CSV file structure.")
                
        except Exception as e:
            st.error(f"❌ Error processing files: {str(e)}")

# Main content area
if st.session_state.processed_data is not None:
    processed_df = st.session_state.processed_data
    
    # Create tabs for better organization
    tab1, tab2 = st.tabs(["🎯 Pick List Generator", "📊 Data Overview"])
    
    with tab1:
        st.header("🎯 Create Custom Pick List")
        
        # Filter section
        col1, col2, col3, col4 = st.columns([2, 2, 2, 1])
        
        with col1:
            customers = sorted(processed_df['Customer'].unique().tolist())
            selected_customers = st.multiselect("Select Customers", customers)
            
        with col2:
            if selected_customers:
                filtered_orders = processed_df[processed_df['Customer'].isin(selected_customers)]['Order_Number'].unique()
            else:
                filtered_orders = processed_df['Order_Number'].unique()
            orders = sorted(filtered_orders.tolist())
            selected_orders = st.multiselect("Select Order Numbers", orders)
            
        with col3:
            if selected_customers:
                filtered_categories = processed_df[processed_df['Customer'].isin(selected_customers)]['Category'].unique()
            elif selected_orders:
                filtered_categories = processed_df[processed_df['Order_Number'].isin(selected_orders)]['Category'].unique()
            else:
                filtered_categories = processed_df['Category'].unique()
            categories = sorted(filtered_categories.tolist())
            selected_categories = st.multiselect("Select Categories", categories)
            
        with col4:
            st.write("")  # Empty space
            st.write("")  # Empty space
            generate_pdf_btn = st.button("📑 Generate PDF", type="primary")
        
        # Apply filters
        filtered_df = processed_df.copy()
        
        applied_filters = {}
        
        if selected_customers:
            filtered_df = filtered_df[filtered_df['Customer'].isin(selected_customers)]
            applied_filters['Customers'] = selected_customers
            
        if selected_orders:
            filtered_df = filtered_df[filtered_df['Order_Number'].isin(selected_orders)]
            applied_filters['Order Numbers'] = selected_orders
            
        if selected_categories:
            filtered_df = filtered_df[filtered_df['Category'].isin(selected_categories)]
            applied_filters['Categories'] = selected_categories
        
        # Show filtered results
        st.subheader(f"📋 Pick List Results ({len(filtered_df):,} records)")
        st.dataframe(filtered_df, use_container_width=True)
        
        # Download section
        col1, col2 = st.columns(2)
        
        with col1:
            # CSV download
            csv = filtered_df.to_csv(index=False)
            st.download_button(
                label="📄 Download CSV",
                data=csv,
                file_name=f"pick_list_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                use_container_width=True
            )
        
        with col2:
            # PDF download (triggered by the button above)
            if generate_pdf_btn:
                with st.spinner("Generating PDF report..."):
                    pdf_buffer = generate_pdf(filtered_df, applied_filters)
                    
                # Immediately trigger download
                st.download_button(
                    label="📑 Download PDF Report",
                    data=pdf_buffer,
                    file_name=f"pick_list_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    key="pdf_download"
                )
                st.success("✅ PDF report generated successfully!")
            else:
                # Show placeholder when PDF not generated
                st.button("📑 Download PDF Report", disabled=True, help="Click 'Generate PDF' button above first", use_container_width=True)
    
    with tab2:
        st.header("📊 Data Overview")
        
        # Summary metrics
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("🛒 Total Orders", len(processed_df['Order_Number'].unique()))
        with col2:
            st.metric("👥 Unique Customers", len(processed_df['Customer'].unique()))
        with col3:
            st.metric("📦 Total Items", len(processed_df))
        with col4:
            st.metric("🏷️ Categories", len(processed_df['Category'].unique()))
        
        # Show breakdown by category
        st.subheader("📈 Category Breakdown")
        category_counts = processed_df['Category'].value_counts()
        st.bar_chart(category_counts)
        
        # Show breakdown by customer
        st.subheader("👥 Customer Breakdown")
        customer_counts = processed_df['Customer'].value_counts().head(10)
        st.bar_chart(customer_counts)
        
        # Show raw data with search
        st.subheader("🔍 Full Dataset")
        st.dataframe(processed_df, use_container_width=True)

else:
    # Welcome screen when no data is loaded
    if not so_file and not assembly_file:
        st.info("👈 Upload both CSV files in the sidebar to get started")
        
        # Show helpful information
        with st.expander("ℹ️ How it Works", expanded=True):
            st.markdown("""
            **📋 Upload** → **🔄 Process** → **🎯 Filter** → **📥 Download**
            
            This tool processes your sales order and assembly data to create custom pick lists with input package tracking.
            
            **Key Features:**
            - 🔗 Links Package Labels to Assembly Numbers
            - 🔍 Finds Input Package Numbers for tracking
            - 📑 Generates formatted PDF reports with pick checkboxes
            - 🎯 Filter by customer, order, or category
            - 📊 Data overview and analytics
            """)
        
        with st.expander("📁 CSV File Requirements"):
            st.markdown("""
            **Sales Order Item History CSV:**
            - Status: Processing orders only
            - Date Range: Past 30 days
            - Required columns: Customer, Order Number, Category, Product, Package Batch Number, Package Label, Quantity
            
            **Assembly Data CSV:**
            - Date Range: Last 3 days
            - Required columns: Input/Output, Package Number, Assembly Number
            - Both input and output records needed for proper linking
            
            *The tool automatically handles metadata lines and column mapping.*
            """)
    
    elif so_file and assembly_file:
        st.info("👈 Click the 'Process Data' button in the sidebar to analyze your files")
    
    else:
        missing_file = "Assembly Data" if so_file else "Sales Order Item History"
        st.warning(f"📁 Please upload the {missing_file} CSV file to continue")