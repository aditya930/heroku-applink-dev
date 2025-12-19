import { LightningElement, api } from 'lwc';
import { ShowToastEvent } from 'lightning/platformShowToastEvent';
import processRecord from '@salesforce/apex/GenerateQuotePDFController.processRecord';

export default class ProcessRecord extends LightningElement {
    currentRecordId;
    isLoading = false;
    
    /*connectedCallback() {
        this.callApexMethod();
    }*/

    get recordId(){
        return this.currentRecordId;
    }

    @api
    set recordId(value) {
        this.currentRecordId = value;
        console.log('this current record Id==', this.currentRecordId);
        this.callApexMethod();
    }

    async callApexMethod() {
        this.isLoading = true;
        try {
            await processRecord({ recordId: this.recordId });
            this.showToast('Success', 'Quote PDF generated successfully!', 'success');
        } catch (error) {
            this.showToast('Error', error.body?.message || 'An error occurred while processing the record.', 'error');
        } finally {
            this.isLoading = false;
        }
    }

    showToast(title, message, variant) {
        const event = new ShowToastEvent({
            title: title,
            message: message,
            variant: variant
        });
        this.dispatchEvent(event);
    }
}